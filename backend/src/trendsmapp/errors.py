"""Typed domain exceptions shared by every layer of the backend.

The exception hierarchy is the only place where an error acquires a stable
machine-readable code. The API layer maps these codes onto HTTP status codes
and the stable error envelope; the worker records the same code on the job.
Messages are written for a human operator and never contain secrets, raw file
contents, or connection strings.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "CompatibilityError",
    "ConfigurationError",
    "ConflictError",
    "DomainError",
    "JobError",
    "NotFoundError",
    "ParsingError",
    "ResourceLimitError",
    "ScientificError",
    "StorageError",
    "TrendsmappError",
    "UnauthorizedError",
    "ValidationError",
]


class TrendsmappError(Exception):
    """Base class for every error raised by the application."""

    code: str = "internal_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = dict(details or {})

    def as_payload(self) -> dict[str, Any]:
        """Return the error as the data carried inside the API envelope."""
        return {"code": self.code, "message": self.message, "details": self.details}


class ConfigurationError(TrendsmappError):
    """Raised when process configuration is missing or inconsistent."""

    code = "configuration_error"


class ValidationError(TrendsmappError):
    """Raised when a request or document violates a contract."""

    code = "validation_error"


class NotFoundError(TrendsmappError):
    """Raised when a referenced resource does not exist."""

    code = "not_found"


class ConflictError(TrendsmappError):
    """Raised when a request conflicts with existing state."""

    code = "conflict"


class UnauthorizedError(TrendsmappError):
    """Raised when a caller cannot be authorized for an operation."""

    code = "unauthorized"


class ResourceLimitError(ValidationError):
    """Raised when a request exceeds a documented resource ceiling."""

    code = "resource_limit_exceeded"


class ParsingError(TrendsmappError):
    """Raised when an input file cannot be parsed without guessing."""

    code = "parsing_error"


class CompatibilityError(TrendsmappError):
    """Raised when a schema or contract version is not supported."""

    code = "incompatible_version"


class StorageError(TrendsmappError):
    """Raised when the object store cannot satisfy a request."""

    code = "storage_error"


class ScientificError(TrendsmappError):
    """Raised when a scientific computation cannot produce a valid result."""

    code = "scientific_error"


class DomainError(TrendsmappError):
    """Raised when a domain invariant would be violated."""

    code = "domain_error"


class JobError(TrendsmappError):
    """Raised when a job cannot be created, claimed, or completed."""

    code = "job_error"
