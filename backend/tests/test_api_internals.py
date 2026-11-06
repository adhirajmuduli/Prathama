"""Tests for the API application factory, dependencies, middleware, and error mapping."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from trendsmapp.api.app import create_app
from trendsmapp.api.dependencies import (
    get_artifact_repository,
    get_dataset_repository,
    get_job_repository,
    get_object_store,
    get_registry_repository,
    get_run_repository,
    get_session,
    get_settings_dependency,
    get_upload_repository,
)
from trendsmapp.api.middleware import BodyLimitMiddleware, current_request_id
from trendsmapp.errors import (
    CompatibilityError,
    ConflictError,
    NotFoundError,
    ResourceLimitError,
    StorageError,
    UnauthorizedError,
    ValidationError,
)
from trendsmapp.persistence.repositories.artifacts import ArtifactRepository
from trendsmapp.persistence.repositories.datasets import DatasetRepository
from trendsmapp.persistence.repositories.jobs import JobRepository
from trendsmapp.persistence.repositories.registries import RegistryRepository
from trendsmapp.persistence.repositories.runs import RunRepository
from trendsmapp.persistence.repositories.uploads import UploadRepository
from trendsmapp.settings import Settings
from trendsmapp.storage.local import LocalObjectStore


def _application(settings: Settings) -> Any:
    return create_app(settings=settings)


async def _client(application: Any, *, raise_app_exceptions: bool = True) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=application, raise_app_exceptions=raise_app_exceptions)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


async def test_application_exposes_its_contract_metadata(settings: Settings) -> None:
    application = _application(settings)
    assert application.title == "Trendsmapp API"
    assert application.openapi_url == "/api/v1/openapi.json"
    assert application.docs_url == "/api/v1/docs"
    document = application.openapi()
    assert document["info"]["version"]
    assert "/api/v1/health/live" in document["paths"]


async def test_lifespan_publishes_the_runtime_state(settings: Settings) -> None:
    application = _application(settings)
    async with application.router.lifespan_context(application):
        assert application.state.settings is settings
        assert application.state.session_factory is not None
        assert isinstance(application.state.object_store, LocalObjectStore)


async def test_cors_middleware_is_installed_only_when_origins_are_configured(
    settings: Settings,
) -> None:
    without_cors = _application(settings.model_copy(update={"cors_allow_origins": []}))
    assert not any(
        middleware.cls.__name__ == "CORSMiddleware" for middleware in without_cors.user_middleware
    )

    with_cors = _application(
        settings.model_copy(update={"cors_allow_origins": ["https://trendsmapp.example"]})
    )
    assert any(
        middleware.cls.__name__ == "CORSMiddleware" for middleware in with_cors.user_middleware
    )


async def test_request_validation_failures_use_the_error_envelope(settings: Settings) -> None:
    application = _application(settings)

    @application.get("/_test/query")
    async def _query(value: int) -> dict[str, int]:
        return {"value": value}

    async with await _client(application) as client:
        response = await client.get("/_test/query?value=not-a-number")
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["details"]["errors"]
    assert body["request_id"] == response.headers["x-request-id"]


async def test_http_exceptions_use_the_error_envelope(settings: Settings) -> None:
    application = _application(settings)

    @application.get("/_test/missing")
    async def _missing() -> None:
        raise HTTPException(status_code=404, detail="The resource is missing.")

    @application.get("/_test/structured")
    async def _structured() -> None:
        raise HTTPException(
            status_code=409,
            detail={"code": "conflict", "message": "The job already exists."},
        )

    async with await _client(application) as client:
        missing = await client.get("/_test/missing")
        structured = await client.get("/_test/structured")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
    assert structured.status_code == 409
    assert structured.json()["error"]["code"] == "conflict"
    assert structured.json()["error"]["message"] == "The job already exists."


async def test_unexpected_failures_return_a_generic_envelope(settings: Settings) -> None:
    application = _application(settings)

    @application.get("/_test/crash")
    async def _crash() -> None:
        raise RuntimeError("private detail")

    async with await _client(application, raise_app_exceptions=False) as client:
        response = await client.get("/_test/crash")
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert "private detail" not in str(body)


@pytest.mark.parametrize(
    ("error", "status_code", "code"),
    [
        (ValidationError("Invalid request."), 422, "validation_error"),
        (ResourceLimitError("Too large."), 413, "resource_limit_exceeded"),
        (NotFoundError("Missing."), 404, "not_found"),
        (ConflictError("Conflict."), 409, "conflict"),
        (UnauthorizedError("Not allowed."), 401, "unauthorized"),
        (CompatibilityError("Unsupported version."), 400, "incompatible_version"),
        (StorageError("Unreachable."), 500, "storage_error"),
    ],
)
async def test_domain_errors_map_to_stable_status_codes(
    settings: Settings,
    error: Exception,
    status_code: int,
    code: str,
) -> None:
    application = _application(settings)

    @application.get("/_test/domain-error")
    async def _domain_error() -> None:
        raise error

    async with await _client(application) as client:
        response = await client.get("/_test/domain-error")
    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code


async def test_streamed_bodies_over_the_limit_are_rejected(settings: Settings) -> None:
    limited = settings.model_copy(update={"request_max_body_bytes": 32})
    application = _application(limited)

    @application.post("/_test/echo")
    async def _echo(payload: bytes = b"") -> dict[str, int]:
        return {"length": len(payload)}

    async with await _client(application) as client:
        response = await client.post(
            "/_test/echo",
            content=b"x" * 64,
            headers={"Content-Type": "application/octet-stream"},
        )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "resource_limit_exceeded"


async def test_an_unparsable_content_length_is_ignored() -> None:
    received: list[bytes] = []

    async def application(scope: Any, receive: Any, send: Any) -> None:
        message = await receive()
        received.append(message.get("body", b""))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    middleware = BodyLimitMiddleware(application, maximum_bytes=32)
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": [(b"content-length", b"not-a-number")],
    }
    incoming = [{"type": "http.request", "body": b"x" * 4}]
    outgoing: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return incoming.pop(0)

    async def send(message: dict[str, Any]) -> None:
        outgoing.append(message)

    await middleware(scope, receive, send)
    assert received == [b"x" * 4]
    assert outgoing[0]["status"] == 200


async def test_request_context_is_reset_after_the_response(settings: Settings) -> None:
    application = _application(settings)
    async with await _client(application) as client:
        await client.get("/api/v1/health/live")
    assert current_request_id() is None


async def test_dependency_providers_return_the_runtime_objects(settings: Settings) -> None:
    application = _application(settings)

    class _Request:
        def __init__(self, app: Any) -> None:
            self.app = app

    async with application.router.lifespan_context(application):
        request = _Request(application)
        assert get_settings_dependency(request) is settings
        assert isinstance(get_object_store(request), LocalObjectStore)

        generator = get_session(request)
        session = await generator.__anext__()
        assert isinstance(session, AsyncSession)
        await generator.aclose()

        assert isinstance(get_dataset_repository(session), DatasetRepository)
        assert isinstance(get_upload_repository(session), UploadRepository)
        assert isinstance(get_job_repository(session), JobRepository)
        assert isinstance(get_run_repository(session), RunRepository)
        assert isinstance(get_artifact_repository(session), ArtifactRepository)
        assert isinstance(get_registry_repository(session), RegistryRepository)
