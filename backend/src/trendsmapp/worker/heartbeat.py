"""Running-job heartbeats and worker-loss detection.

A running job records a heartbeat at every stage boundary. A worker that
dies stops heartbeating, and the queue returns its jobs to the queue once the
heartbeat is older than the configured staleness window.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from trendsmapp.clock import utc_now
from trendsmapp.persistence.database import session_scope
from trendsmapp.persistence.repositories.jobs import JobRepository

__all__ = ["HeartbeatMonitor"]


class HeartbeatMonitor:
    """Refreshes job heartbeats and reports whether a job stopped beating."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        stale_after_seconds: int,
    ) -> None:
        self._session_factory = session_factory
        self._stale_after_seconds = stale_after_seconds

    async def beat(self, job_id: str) -> None:
        """Record a heartbeat for a running job."""
        async with session_scope(self._session_factory) as session:
            repository = JobRepository(session)
            await repository.heartbeat(job_id)

    async def record_progress(self, job_id: str, *, progress: float, stage: str | None) -> None:
        """Record progress and refresh the heartbeat of a running job."""
        async with session_scope(self._session_factory) as session:
            repository = JobRepository(session)
            await repository.record_progress(job_id, progress=progress, stage=stage)

    def is_stale(self, heartbeat_at: datetime | None, *, now: datetime | None = None) -> bool:
        """Return whether a heartbeat is older than the staleness window."""
        if heartbeat_at is None:
            return True
        reference = now or utc_now()
        age_seconds = (reference - heartbeat_at).total_seconds()
        return age_seconds > self._stale_after_seconds
