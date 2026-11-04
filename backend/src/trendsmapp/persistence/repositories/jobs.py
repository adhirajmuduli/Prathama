"""Job creation, claiming, progress, cancellation, heartbeat, and terminal state.

Jobs are the durable boundary between the API process and the worker. The API
only writes rows; the worker only claims and completes them. Claiming uses
``FOR UPDATE SKIP LOCKED`` on PostgreSQL so that several workers can poll the
same table without handing the same job to two processes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Result, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from trendsmapp.clock import utc_now
from trendsmapp.domain.enums import JobStatus, JobType
from trendsmapp.errors import ConflictError, NotFoundError
from trendsmapp.persistence.models import JobRow

__all__ = ["JobRepository"]


def _affected_rows(result: Result[Any]) -> int:
    """Return the number of rows changed by a data-modifying statement."""
    if isinstance(result, CursorResult):
        return int(result.rowcount or 0)
    return 0


class JobRepository:
    """Reads and writes durable job rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        job_type: JobType,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
        request_hash: str | None = None,
        run_id: str | None = None,
        dataset_version_id: str | None = None,
        job_id: str | None = None,
    ) -> tuple[JobRow, bool]:
        """Create a queued job.

        Returns the job row and whether it was newly created. When an
        idempotency key is supplied and an existing job has the same key, the
        existing job is returned unchanged; a different request hash under the
        same key is a conflict.
        """
        if idempotency_key:
            existing = await self.find_by_idempotency_key(idempotency_key)
            if existing is not None:
                if request_hash is not None and existing.request_hash != request_hash:
                    raise ConflictError(
                        "The idempotency key was already used with a different request.",
                        details={"idempotency_key": idempotency_key, "job_id": existing.id},
                    )
                return existing, False
        row = JobRow(
            id=job_id or _new_job_id(),
            job_type=job_type.value,
            status=JobStatus.QUEUED.value,
            payload=payload,
            progress=0.0,
            attempts=0,
            cancel_requested=False,
            run_id=run_id,
            dataset_version_id=dataset_version_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            created_at=utc_now(),
        )
        self._session.add(row)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            await self._session.rollback()
            raise ConflictError(
                "A job with the same idempotency key already exists.",
                details={"idempotency_key": idempotency_key},
            ) from exc
        return row, True

    async def find_by_idempotency_key(self, idempotency_key: str) -> JobRow | None:
        """Return the job registered under an idempotency key, if any."""
        result = await self._session.execute(
            select(JobRow).where(JobRow.idempotency_key == idempotency_key)
        )
        return result.scalar_one_or_none()

    async def get(self, job_id: str) -> JobRow | None:
        """Return a job by identifier."""
        return await self._session.get(JobRow, job_id)

    async def require(self, job_id: str) -> JobRow:
        """Return a job by identifier, raising when it does not exist."""
        row = await self.get(job_id)
        if row is None:
            raise NotFoundError("The requested job does not exist.", details={"job_id": job_id})
        return row

    async def claim_next(
        self,
        *,
        worker_id: str,
        job_types: tuple[JobType, ...] | None = None,
    ) -> JobRow | None:
        """Atomically claim the oldest queued job and return it.

        The claim marks the job as running in the same transaction that
        selected it, so a second worker cannot observe the same job as
        queued.
        """
        now = utc_now()
        statement = select(JobRow).where(JobRow.status == JobStatus.QUEUED.value)
        if job_types:
            statement = statement.where(JobRow.job_type.in_([item.value for item in job_types]))
        statement = statement.order_by(JobRow.created_at, JobRow.id).limit(1)
        if self._supports_skip_locked():
            statement = statement.with_for_update(skip_locked=True)
        result = await self._session.execute(statement)
        row = result.scalars().first()
        if row is None:
            return None
        update_result = await self._session.execute(
            update(JobRow)
            .where(JobRow.id == row.id, JobRow.status == JobStatus.QUEUED.value)
            .values(
                status=JobStatus.RUNNING.value,
                worker_id=worker_id,
                started_at=now,
                heartbeat_at=now,
                attempts=JobRow.attempts + 1,
            )
        )
        if _affected_rows(update_result) != 1:
            await self._session.rollback()
            return None
        await self._session.flush()
        await self._session.refresh(row)
        return row

    async def record_progress(
        self,
        job_id: str,
        *,
        progress: float,
        stage: str | None = None,
    ) -> None:
        """Record progress and the current stage of a running job."""
        bounded = min(max(progress, 0.0), 1.0)
        await self._session.execute(
            update(JobRow)
            .where(JobRow.id == job_id)
            .values(progress=bounded, stage=stage, heartbeat_at=utc_now())
        )

    async def heartbeat(self, job_id: str) -> None:
        """Refresh the heartbeat timestamp of a running job."""
        await self._session.execute(
            update(JobRow).where(JobRow.id == job_id).values(heartbeat_at=utc_now())
        )

    async def complete(self, job_id: str, result: dict[str, Any]) -> None:
        """Mark a job as succeeded and store its result."""
        await self._session.execute(
            update(JobRow)
            .where(JobRow.id == job_id)
            .values(
                status=JobStatus.SUCCEEDED.value,
                result=result,
                progress=1.0,
                finished_at=utc_now(),
                heartbeat_at=utc_now(),
            )
        )

    async def fail(self, job_id: str, error: dict[str, Any]) -> None:
        """Mark a job as failed and store its structured error."""
        await self._session.execute(
            update(JobRow)
            .where(JobRow.id == job_id)
            .values(
                status=JobStatus.FAILED.value,
                error=error,
                finished_at=utc_now(),
                heartbeat_at=utc_now(),
            )
        )

    async def request_cancel(self, job_id: str) -> bool:
        """Request cancellation of a job; returns whether the job was cancelable."""
        result = await self._session.execute(
            update(JobRow)
            .where(
                JobRow.id == job_id,
                JobRow.status.in_([JobStatus.QUEUED.value, JobStatus.RUNNING.value]),
            )
            .values(cancel_requested=True)
        )
        return _affected_rows(result) == 1

    async def mark_cancelled(self, job_id: str) -> None:
        """Mark a job as cancelled."""
        await self._session.execute(
            update(JobRow)
            .where(JobRow.id == job_id)
            .values(
                status=JobStatus.CANCELLED.value,
                finished_at=utc_now(),
                heartbeat_at=utc_now(),
            )
        )

    async def recover_stale(self, *, stale_before: datetime) -> int:
        """Return running jobs whose heartbeat expired to the queued state."""
        result = await self._session.execute(
            update(JobRow)
            .where(
                JobRow.status == JobStatus.RUNNING.value,
                JobRow.heartbeat_at.is_not(None),
                JobRow.heartbeat_at < stale_before,
            )
            .values(
                status=JobStatus.QUEUED.value,
                worker_id=None,
                heartbeat_at=None,
                started_at=None,
            )
        )
        return _affected_rows(result)

    def _supports_skip_locked(self) -> bool:
        """Return whether the bound dialect supports row locking with SKIP LOCKED."""
        try:
            bind = self._session.get_bind()
        except Exception:  # noqa: BLE001 - unbound sessions fall back to a plain select
            return False
        dialect = getattr(bind, "dialect", None)
        name = getattr(dialect, "name", "")
        return name in {"postgresql", "mysql", "mariadb"}


def _new_job_id() -> str:
    from trendsmapp.domain.identifiers import new_job_id

    return new_job_id()
