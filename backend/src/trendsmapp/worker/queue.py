"""PostgreSQL transactional job claiming with stale-job recovery.

The queue is a thin layer over :class:`~trendsmapp.persistence.repositories.jobs.JobRepository`.
It owns the transaction boundaries: a claim is committed before the job is
executed, so a crash during execution cannot leave the row locked.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from trendsmapp.clock import utc_now
from trendsmapp.domain.enums import JobType
from trendsmapp.persistence.database import session_scope
from trendsmapp.persistence.models import JobRow
from trendsmapp.persistence.repositories.jobs import JobRepository

__all__ = ["JobQueue"]


class JobQueue:
    """Claims jobs for execution and recovers jobs abandoned by a lost worker."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def claim(
        self,
        *,
        worker_id: str,
        job_types: tuple[JobType, ...] | None = None,
    ) -> JobRow | None:
        """Claim the oldest queued job and commit the claim."""
        async with session_scope(self._session_factory) as session:
            repository = JobRepository(session)
            job = await repository.claim_next(worker_id=worker_id, job_types=job_types)
            return job

    async def recover_stale(self, *, stale_after_seconds: int) -> int:
        """Return abandoned running jobs to the queue."""
        cutoff = utc_now() - timedelta(seconds=stale_after_seconds)
        async with session_scope(self._session_factory) as session:
            repository = JobRepository(session)
            return await repository.recover_stale(stale_before=cutoff)

    async def get(self, job_id: str) -> JobRow | None:
        """Return a job row without claiming it."""
        async with session_scope(self._session_factory) as session:
            repository = JobRepository(session)
            return await repository.get(job_id)

    async def cancel_requested(self, job_id: str) -> bool:
        """Return whether cancellation was requested for a job."""
        async with session_scope(self._session_factory) as session:
            repository = JobRepository(session)
            job = await repository.get(job_id)
            return bool(job is not None and job.cancel_requested)

    @staticmethod
    def stale_cutoff(stale_after_seconds: int, *, now: datetime | None = None) -> datetime:
        """Return the heartbeat cutoff below which a running job is considered stale."""
        return (now or utc_now()) - timedelta(seconds=stale_after_seconds)
