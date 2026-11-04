"""Structured logging with request and job correlation identifiers.

One configuration is used by the API, the worker, and the CLI so that a log
line means the same thing everywhere. Secret-bearing keys are redacted before
serialization, and correlation identifiers are carried in context variables so
that a handler deep in the call stack can bind them without threading them
through every signature.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Mapping, MutableMapping
from typing import Any, cast

import structlog
from structlog.typing import Processor

__all__ = [
    "bind_job_context",
    "bind_request_context",
    "clear_context",
    "configure_logging",
    "get_logger",
    "redact_event",
]

_REDACTED_KEY_FRAGMENTS = (
    "authorization",
    "cookie",
    "credential",
    "password",
    "secret",
    "session",
    "token",
    "api_key",
    "access_key",
    "private_key",
)

_REDACTION_PLACEHOLDER = "[redacted]"


def _is_secret_key(key: str) -> bool:
    lowered = key.lower()
    return any(fragment in lowered for fragment in _REDACTED_KEY_FRAGMENTS)


def redact_event(
    _logger: Any, _method_name: str, event_dict: MutableMapping[str, Any]
) -> Mapping[str, Any]:
    """Replace secret-bearing values with a placeholder."""
    for key in list(event_dict):
        if _is_secret_key(key) and event_dict[key] is not None:
            event_dict[key] = _REDACTION_PLACEHOLDER
    return event_dict


def configure_logging(*, level: str = "info", json_output: bool = True) -> None:
    """Configure the process-wide logging pipeline.

    The standard library root logger is redirected to ``stderr`` so that
    container logs stay readable, and structlog is configured with the same
    processors in both modes.
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", stream=sys.stderr, level=numeric_level)
    for noisy in ("uvicorn.access", "uvicorn.error", "sqlalchemy.engine"):
        logging.getLogger(noisy).setLevel(max(numeric_level, logging.WARNING))

    renderer: Processor
    if json_output:
        renderer = structlog.processors.JSONRenderer(ensure_ascii=False)
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=False)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            redact_event,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    structlog.contextvars.clear_contextvars()


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a bound logger for ``name``."""
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(name))


def bind_request_context(request_id: str) -> None:
    """Bind the current request identifier to the logging context."""
    structlog.contextvars.bind_contextvars(request_id=request_id)


def bind_job_context(job_id: str, run_id: str | None = None) -> None:
    """Bind the current job (and optionally run) identifier to the logging context."""
    if run_id is None:
        structlog.contextvars.bind_contextvars(job_id=job_id)
    else:
        structlog.contextvars.bind_contextvars(job_id=job_id, run_id=run_id)


def clear_context() -> None:
    """Clear the correlation context, for example between worker jobs."""
    structlog.contextvars.clear_contextvars()
