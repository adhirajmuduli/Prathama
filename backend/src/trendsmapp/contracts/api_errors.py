"""The stable machine-readable API error envelope.

Every failure returned by the HTTP API uses this shape, including failures
raised inside the database, the object store, and the scientific layers. The
``code`` is stable and machine-readable; the ``message`` is written for an
operator; ``details`` carries structured context that never includes secrets,
raw file contents, or stack traces.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["ApiError", "ErrorCode", "ErrorEnvelope"]

ErrorCode = Literal[
    "validation_error",
    "resource_limit_exceeded",
    "not_found",
    "method_not_allowed",
    "conflict",
    "unauthorized",
    "forbidden",
    "incompatible_version",
    "parsing_error",
    "storage_error",
    "scientific_error",
    "domain_error",
    "job_error",
    "configuration_error",
    "rate_limited",
    "internal_error",
]


class ApiError(BaseModel):
    """The error description carried inside the envelope."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: ErrorCode
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorEnvelope(BaseModel):
    """The response body returned for every failed request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    error: ApiError
    request_id: str | None = None
