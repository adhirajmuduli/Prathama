"""API tests for health, capabilities, contracts, and error envelopes."""

from __future__ import annotations

import httpx

from trendsmapp.contracts.versions import API_MAJOR_VERSION, APPLICATION_VERSION


async def test_liveness_is_public_and_minimal(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "trendsmapp"}


async def test_readiness_reports_its_components(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["components"]["database"] == "ok"
    assert body["components"]["object_store"] == "ok"


async def test_capabilities_report_versions_and_limits(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/capabilities")
    assert response.status_code == 200
    body = response.json()
    assert body["api_major"] == API_MAJOR_VERSION
    assert body["application_version"] == APPLICATION_VERSION
    assert body["limits"]["upload_max_bytes"] > 0
    assert body["configuration"]["analysis_crs"] == "EPSG:32644"


async def test_contract_versions_endpoint_lists_supported_versions(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/api/v1/contracts/versions")
    assert response.status_code == 200
    body = response.json()
    assert body["api_major"] == API_MAJOR_VERSION
    assert body["supported_api_majors"] == [API_MAJOR_VERSION]
    assert body["supported_artifact_schema_versions"] == ["1.0.0"]


async def test_unknown_route_returns_the_error_envelope(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "not_found"
    assert body["request_id"] == response.headers["x-request-id"]


async def test_request_id_is_echoed_when_supplied(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/health/live", headers={"X-Request-ID": "abc-123"})
    assert response.headers["x-request-id"] == "abc-123"


async def test_invalid_request_id_is_replaced(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/health/live", headers={"X-Request-ID": "not valid!"})
    assert response.headers["x-request-id"] != "not valid!"


async def test_security_headers_are_present(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/health/live")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"


async def test_oversized_bodies_are_rejected_with_a_structured_error(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        "/api/v1/capabilities",
        content=b"x" * (17 * 1024 * 1024),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413
    body = response.json()
    assert body["error"]["code"] == "resource_limit_exceeded"


async def test_openapi_document_is_generated_at_the_versioned_path(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/api/v1/openapi.json")
    assert response.status_code == 200
    document = response.json()
    assert document["info"]["version"] == APPLICATION_VERSION
    assert "/api/v1/health/live" in document["paths"]


async def test_supported_method_returns_the_payload(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_unsupported_methods_use_the_envelope(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/health/live")
    assert response.status_code == 405
    body = response.json()
    assert body["error"]["code"] == "method_not_allowed"
    assert body["request_id"] == response.headers["x-request-id"]
