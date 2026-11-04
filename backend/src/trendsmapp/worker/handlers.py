"""Dispatch of claimed jobs through the workflow registry.

The registry maps a job type to the exact handler that executes it. A job
whose type has no registered handler fails with a structured
``unsupported_job_type`` error: the worker never guesses a handler and never
reports a job as successful without executing it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from trendsmapp.domain.enums import JobType
from trendsmapp.errors import JobError
from trendsmapp.settings import Settings
from trendsmapp.storage.base import ObjectStore
from trendsmapp.worker.heartbeat import HeartbeatMonitor

__all__ = ["JobExecutionContext", "JobHandler", "JobHandlerRegistry"]


@dataclass(frozen=True, slots=True)
class JobExecutionContext:
    """Everything a handler needs to execute one job."""

    job_id: str
    job_type: JobType
    payload: dict[str, Any]
    run_id: str | None
    dataset_version_id: str | None
    seed: int
    settings: Settings
    object_store: ObjectStore
    session_factory: async_sessionmaker[AsyncSession]
    heartbeat: HeartbeatMonitor
    cancellation_probe: Callable[[], Awaitable[bool]]
    metadata: dict[str, Any] = field(default_factory=dict)


class JobHandler(Protocol):
    """Executes one job and returns its result payload."""

    async def __call__(self, context: JobExecutionContext) -> dict[str, Any]:
        """Execute the job described by ``context``."""
        ...


class JobHandlerRegistry:
    """Maps job types to their execution handlers."""

    def __init__(self) -> None:
        self._handlers: dict[JobType, JobHandler] = {}

    def register(self, job_type: JobType, handler: JobHandler) -> None:
        """Register the handler for a job type."""
        if job_type in self._handlers:
            raise ValueError(f"A handler is already registered for job type '{job_type}'.")
        self._handlers[job_type] = handler

    def supports(self, job_type: JobType) -> bool:
        """Return whether a handler is registered for a job type."""
        return job_type in self._handlers

    @property
    def registered_types(self) -> tuple[JobType, ...]:
        """Return every job type that has a handler."""
        return tuple(self._handlers)

    async def dispatch(self, context: JobExecutionContext) -> dict[str, Any]:
        """Execute the handler registered for the context's job type."""
        handler = self._handlers.get(context.job_type)
        if handler is None:
            raise JobError(
                f"No workflow is registered for job type '{context.job_type}'.",
                details={
                    "job_type": context.job_type.value,
                    "registered_job_types": [item.value for item in self.registered_types],
                },
            )
        return await handler(context)
