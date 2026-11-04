"""Worker lifecycle tests covering execution, failure, and cancellation."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from trendsmapp.clock import utc_now
from trendsmapp.domain.enums import JobStatus, JobType
from trendsmapp.errors import JobError, ScientificError
from trendsmapp.persistence.database import session_scope
from trendsmapp.persistence.repositories.jobs import JobRepository
from trendsmapp.settings import Settings
from trendsmapp.storage.base import StoredObject, StoredObjectStream
from trendsmapp.worker.handlers import JobExecutionContext, JobHandlerRegistry
from trendsmapp.worker.heartbeat import HeartbeatMonitor
from trendsmapp.worker.main import Worker
from trendsmapp.worker.queue import JobQueue


class _UnreachableStore:
    """An object store whose probes always fail."""

    def put_bytes(self, key: str, payload: bytes, *, content_type: str) -> StoredObject:
        raise AssertionError("the unreachable store must not be written to")

    def put_stream(
        self, key: str, stream: Any, *, content_type: str, expected_size: int | None = None
    ) -> StoredObject:
        raise AssertionError("the unreachable store must not be written to")

    def get_bytes(self, key: str) -> bytes:
        raise AssertionError("the unreachable store must not be read")

    def open_stream(self, key: str) -> StoredObjectStream:
        raise AssertionError("the unreachable store must not be read")

    def exists(self, key: str) -> bool:
        return False

    def head(self, key: str) -> StoredObject:
        raise AssertionError("the unreachable store must not be read")

    def delete(self, key: str) -> None:
        raise AssertionError("the unreachable store must not be deleted")

    def list_prefix(self, prefix: str) -> Any:
        raise AssertionError("the unreachable store must not be listed")

    def ping(self) -> bool:
        return False


async def _create_job(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    job_type: JobType = JobType.ANALYZE,
    payload: dict[str, Any] | None = None,
) -> str:
    async with session_scope(session_factory) as session:
        repository = JobRepository(session)
        row, _created = await repository.create(job_type=job_type, payload=payload or {})
        return row.id


async def _job_row(
    session_factory: async_sessionmaker[AsyncSession], job_id: str
) -> dict[str, Any]:
    async with session_scope(session_factory) as session:
        repository = JobRepository(session)
        row = await repository.get(job_id)
        assert row is not None
        return {
            "status": row.status,
            "result": row.result,
            "error": row.error,
            "progress": row.progress,
        }


async def test_worker_startup_requires_a_reachable_object_store(
    settings: Settings, engine: AsyncEngine
) -> None:
    worker = Worker(settings=settings, engine=engine, object_store=_UnreachableStore())
    with pytest.raises(JobError):
        await worker.startup()
    assert worker.worker_id.startswith("worker-")
    assert worker.registry.registered_types == ()


async def test_worker_executes_a_registered_job(
    settings: Settings,
    prepared_database: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    registry = JobHandlerRegistry()
    seen: list[str] = []

    async def handler(context: JobExecutionContext) -> dict[str, Any]:
        seen.append(context.job_id)
        assert context.job_type is JobType.ANALYZE
        assert context.seed == 7
        return {"artifact_count": 2}

    registry.register(JobType.ANALYZE, handler)
    worker = Worker(
        settings=settings, engine=prepared_database, registry=registry, worker_id="worker-test"
    )
    await worker.startup()

    job_id = await _create_job(session_factory, payload={"seed": 7})
    assert await worker.run_once() is True
    assert seen == [job_id]

    row = await _job_row(session_factory, job_id)
    assert row["status"] == JobStatus.SUCCEEDED.value
    assert row["result"] == {"artifact_count": 2}
    assert row["progress"] == 1.0


async def test_worker_records_a_structured_failure_for_a_scientific_error(
    settings: Settings,
    prepared_database: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    registry = JobHandlerRegistry()

    async def handler(_context: JobExecutionContext) -> dict[str, Any]:
        raise ScientificError(
            "The variogram could not be fitted.", details={"reason": "degenerate"}
        )

    registry.register(JobType.ANALYZE, handler)
    worker = Worker(
        settings=settings, engine=prepared_database, registry=registry, worker_id="worker-test"
    )
    await worker.startup()

    job_id = await _create_job(session_factory)
    assert await worker.run_once() is True
    row = await _job_row(session_factory, job_id)
    assert row["status"] == JobStatus.FAILED.value
    assert row["error"] is not None
    assert row["error"]["code"] == "scientific_error"
    assert row["error"]["details"] == {"reason": "degenerate"}


async def test_worker_records_an_internal_failure_for_an_unexpected_error(
    settings: Settings,
    prepared_database: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    registry = JobHandlerRegistry()

    async def handler(_context: JobExecutionContext) -> dict[str, Any]:
        raise RuntimeError("private failure detail")

    registry.register(JobType.ANALYZE, handler)
    worker = Worker(
        settings=settings, engine=prepared_database, registry=registry, worker_id="worker-test"
    )
    await worker.startup()

    job_id = await _create_job(session_factory)
    assert await worker.run_once() is True
    row = await _job_row(session_factory, job_id)
    assert row["status"] == JobStatus.FAILED.value
    assert row["error"] is not None
    assert row["error"]["code"] == "internal_error"
    assert "private failure detail" not in str(row["error"])


async def test_worker_fails_a_job_whose_type_is_unknown(
    settings: Settings,
    prepared_database: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    registry = JobHandlerRegistry()
    worker = Worker(
        settings=settings, engine=prepared_database, registry=registry, worker_id="worker-test"
    )
    await worker.startup()

    job_id = await _create_job(session_factory, job_type=JobType.ANALYZE)
    async with session_scope(session_factory) as session:
        repository = JobRepository(session)
        row = await repository.get(job_id)
        assert row is not None
        row.job_type = "not_a_job_type"
        await session.commit()

    assert await worker.run_once() is True
    recorded = await _job_row(session_factory, job_id)
    assert recorded["status"] == JobStatus.FAILED.value
    assert recorded["error"] is not None
    assert recorded["error"]["code"] == "job_error"


async def test_worker_cancels_a_job_before_it_starts(
    settings: Settings,
    prepared_database: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    registry = JobHandlerRegistry()
    executed: list[str] = []

    async def handler(context: JobExecutionContext) -> dict[str, Any]:
        executed.append(context.job_id)
        return {}

    registry.register(JobType.ANALYZE, handler)
    worker = Worker(
        settings=settings, engine=prepared_database, registry=registry, worker_id="worker-test"
    )
    await worker.startup()

    job_id = await _create_job(session_factory)
    async with session_scope(session_factory) as session:
        repository = JobRepository(session)
        assert await repository.request_cancel(job_id) is True

    assert await worker.run_once() is True
    assert executed == []
    row = await _job_row(session_factory, job_id)
    assert row["status"] == JobStatus.CANCELLED.value


async def test_worker_reports_no_work_when_the_queue_is_empty(
    settings: Settings,
    prepared_database: AsyncEngine,
) -> None:
    worker = Worker(settings=settings, engine=prepared_database, worker_id="worker-test")
    await worker.startup()
    assert await worker.run_once() is False


async def test_worker_stops_when_a_stop_is_requested(
    settings: Settings,
    prepared_database: AsyncEngine,
) -> None:
    worker = Worker(settings=settings, engine=prepared_database, worker_id="worker-test")
    worker.request_stop()
    await worker.run_forever()
    assert worker.worker_id == "worker-test"


async def test_worker_shutdown_releases_the_engine_it_owns(settings: Settings) -> None:
    worker = Worker(settings=settings, worker_id="worker-test")
    await worker.shutdown()


async def test_heartbeat_monitor_records_progress_and_detects_stale_jobs(
    prepared_database: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    job_id = await _create_job(session_factory)
    monitor = HeartbeatMonitor(session_factory, stale_after_seconds=30)
    await monitor.record_progress(job_id, progress=0.5, stage="parsing")
    await monitor.beat(job_id)

    async with session_scope(session_factory) as session:
        repository = JobRepository(session)
        row = await repository.get(job_id)
        assert row is not None
        assert row.progress == 0.5
        assert row.stage == "parsing"
        assert row.heartbeat_at is not None

    now = utc_now()
    assert monitor.is_stale(None, now=now) is True
    assert monitor.is_stale(now, now=now) is False
    assert monitor.is_stale(now - timedelta(seconds=31), now=now) is True


async def test_job_queue_exposes_job_state_without_claiming(
    prepared_database: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    job_id = await _create_job(session_factory)
    queue = JobQueue(session_factory)
    row = await queue.get(job_id)
    assert row is not None
    assert row.status == JobStatus.QUEUED.value
    assert await queue.cancel_requested(job_id) is False
    cutoff = JobQueue.stale_cutoff(30, now=utc_now())
    assert cutoff < utc_now()
