"""Mapping of typed exceptions onto stable error envelopes.

Every failure leaves the API through one of these handlers, so a client can
always rely on the same envelope shape and a stable machine-readable code.
Internal failures never disclose stack traces, SQL text, connection strings,
or file contents.
"""

from __future__ import annotations

from typing import Any, cast, get_args

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from trendsmapp.api.middleware import current_request_id
from trendsmapp.contracts.api_errors import ApiError, ErrorCode, ErrorEnvelope
from trendsmapp.errors import (
    CompatibilityError,
    ConfigurationError,
    ConflictError,
    DomainError,
    JobError,
    NotFoundError,
    ParsingError,
    ResourceLimitError,
    ScientificError,
    StorageError,
    TrendsmappError,
    UnauthorizedError,
    ValidationError,
)
from trendsmapp.logging_config import get_logger

__all__ = ["install_exception_handlers"]

logger = get_logger(__name__)

_STATUS_BY_ERROR_TYPE: dict[type[TrendsmappError], int] = {
    ValidationError: 422,
    ResourceLimitError: 413,
    ParsingError: 422,
    NotFoundError: 404,
    ConflictError: 409,
    UnauthorizedError: 401,
    CompatibilityError: 400,
    ScientificError: 422,
    DomainError: 422,
    JobError: 409,
    StorageError: 500,
    ConfigurationError: 500,
}


_HTTP_STATUS_TO_ERROR_CODE: dict[int, ErrorCode] = {
    400: "validation_error",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "resource_limit_exceeded",
    415: "validation_error",
    422: "validation_error",
    429: "rate_limited",
}


def _status_for(error: TrendsmappError) -> int:
    """Return the HTTP status for an error, honouring the most specific type."""
    status = _STATUS_BY_ERROR_TYPE.get(type(error))
    if status is not None:
        return status
    for error_type in type(error).__mro__:
        status = _STATUS_BY_ERROR_TYPE.get(error_type)
        if status is not None:
            return status
    return 500


_KNOWN_ERROR_CODES = frozenset(get_args(ErrorCode))


def _envelope(
    code: ErrorCode, message: str, details: dict[str, Any] | None = None
) -> ErrorEnvelope:
    return ErrorEnvelope(
        error=ApiError(code=code, message=message, details=dict(details or {})),
        request_id=current_request_id(),
    )


def install_exception_handlers(app: FastAPI) -> None:
    """Register the exception handlers on ``app``."""

    @app.exception_handler(TrendsmappError)
    async def handle_domain_error(_request: Request, exc: TrendsmappError) -> JSONResponse:
        status_code = _status_for(exc)
        if status_code >= 500:
            logger.error("request_failed", code=exc.code, message=exc.message)
        else:
            logger.info("request_rejected", code=exc.code, message=exc.message)
        envelope = _envelope(cast(ErrorCode, exc.code), exc.message, exc.details)
        return JSONResponse(status_code=status_code, content=envelope.model_dump(mode="json"))

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = [
            {
                "location": ".".join(str(part) for part in error.get("loc", ())),
                "message": error.get("msg", "Invalid value"),
                "type": error.get("type", "value_error"),
            }
            for error in exc.errors()
        ]
        envelope = _envelope(
            "validation_error",
            "The request did not satisfy the contract.",
            {"errors": errors},
        )
        return JSONResponse(status_code=422, content=envelope.model_dump(mode="json"))

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        default_code = _HTTP_STATUS_TO_ERROR_CODE.get(exc.status_code)
        if default_code is None:
            default_code = "internal_error" if exc.status_code >= 500 else "validation_error"
        detail: object = exc.detail
        if isinstance(detail, dict):
            candidate = str(detail.get("code", ""))
            code = candidate if candidate in _KNOWN_ERROR_CODES else default_code
            message = str(detail.get("message", "The request was rejected."))
            raw_details = detail.get("details", {})
            details: dict[str, Any] = dict(raw_details) if isinstance(raw_details, dict) else {}
        else:
            code = default_code
            message = str(detail)
            details = {}
        envelope = _envelope(cast(ErrorCode, code), message, details)
        headers = dict(exc.headers or {})
        return JSONResponse(
            status_code=exc.status_code,
            content=envelope.model_dump(mode="json"),
            headers=headers,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_request: Request, exc: Exception) -> JSONResponse:
        logger.error("unhandled_exception", error_type=type(exc).__name__)
        envelope = _envelope(
            "internal_error",
            "The request could not be completed because of an internal error.",
        )
        return JSONResponse(status_code=500, content=envelope.model_dump(mode="json"))
