"""FastAPI application factory.

The factory owns the process lifecycle: it creates the database engine, the
session factory, and the object store, installs the middleware stack and the
error handlers, and registers the routers. Route handlers never construct
services themselves, and no scientific computation happens inside the API
process.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from trendsmapp.api.exception_handlers import install_exception_handlers
from trendsmapp.api.middleware import (
    BodyLimitMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from trendsmapp.api.routers import (
    analyses,
    capabilities,
    datasets,
    exports,
    health,
    jobs,
    models,
    uploads,
)
from trendsmapp.logging_config import configure_logging, get_logger
from trendsmapp.persistence.database import (
    create_engine_for_settings,
    create_session_factory,
    dispose_engine,
)
from trendsmapp.settings import Settings, get_settings
from trendsmapp.storage.factory import create_object_store
from trendsmapp.version import APPLICATION_VERSION

__all__ = ["create_app"]

_DESCRIPTION = """
The Trendsmapp scientific API.

Uploads are chunked and content-addressed, datasets are normalized into a
canonical observation model, and every analysis runs in the worker process.
Route handlers validate and delegate; they never perform scientific
computation.
""".strip()


def create_app(*, settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI application."""
    resolved = settings or get_settings()
    configure_logging(level=resolved.log_level, json_output=resolved.log_json)
    logger = get_logger(__name__)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        engine = create_engine_for_settings(resolved)
        application.state.settings = resolved
        application.state.engine = engine
        application.state.session_factory = create_session_factory(engine)
        application.state.object_store = create_object_store(resolved)
        logger.info(
            "application_started",
            environment=resolved.environment,
            object_store=resolved.object_store_backend,
        )
        try:
            yield
        finally:
            await dispose_engine(engine)
            logger.info("application_stopped")

    application = FastAPI(
        title="Trendsmapp API",
        version=APPLICATION_VERSION,
        summary="Validated environmental spatial analysis and machine learning.",
        description=_DESCRIPTION,
        lifespan=lifespan,
        openapi_url="/api/v1/openapi.json",
        docs_url="/api/v1/docs",
        redoc_url="/api/v1/redoc",
    )

    application.add_middleware(SecurityHeadersMiddleware)
    application.add_middleware(BodyLimitMiddleware, maximum_bytes=resolved.request_max_body_bytes)
    if resolved.cors_allow_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=list(resolved.cors_allow_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=[
                "Authorization",
                "Content-Type",
                "Content-Range",
                "X-Request-ID",
                "X-Trendsmapp-Api-Version",
                "X-Trendsmapp-Recipe-Schema-Version",
                "X-Trendsmapp-Idempotency-Key",
                "Idempotency-Key",
            ],
            expose_headers=["X-Request-ID"],
        )
    application.add_middleware(TrustedHostMiddleware, allowed_hosts=list(resolved.trusted_hosts))
    application.add_middleware(RequestContextMiddleware)

    install_exception_handlers(application)
    application.include_router(health.router)
    application.include_router(capabilities.router)
    application.include_router(uploads.router)
    application.include_router(jobs.router)
    application.include_router(datasets.router)
    application.include_router(analyses.router)
    application.include_router(models.router)
    application.include_router(exports.router)
    return application
