"""Tests for the durable job lifecycle and the worker process."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from trendsmapp.clock import utc_now
from trendsmapp.domain.enums import JobStatus, JobType
from trendsmapp.errors import ConflictError
from trendsmapp.persistence.database import session_scope
from trendsmapp.persistence.models import JobRow
from trendsmapp.persistence.repositories.jobs import JobRepository
from trendsmapp.settings import Settings
from trendsmapp.storage.local import LocalObjectStore
from trendsmapp.worker.handlers import JobExecutionContext, JobHandlerRegistry
from trendsmapp.worker.main import Worker
from trendsmapp.worker.queue import JobQueue


async def _create_job(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    job_type: JobType = JobType.ANALYZE,
    payload: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
    request_hash: str | None = None,
) -> str:
    async with session_scope(session_factory) as session:
        repository = JobRepository(session)
        row, _created = await repository.create(
            job_type=job_type,
            payload=payload or {},
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        return row.id


async def test_claiming_a_job_marks_it_running(
    prepared_database: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    job_id = await _create_job(session_factory)
    queue = JobQueue(session_factory)
    claimed = await queue.claim(worker_id="worker-1")
    assert claimed is not None
    assert claimed.id == job_id
    assert claimed.status == JobStatus.RUNNING.value
    assert claimed.worker_id == "worker-1"
    assert claimed.attempts == 1


async def test_a_claimed_job_is_not_claimed_twice(
    prepared_database: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _create_job(session_factory)
    queue = JobQueue(session_factory)
    assert await queue.claim(worker_id="worker-1") is not None
    assert await queue.claim(worker_id="worker-2") is None


async def test_idempotency_key_returns_the_original_job(
    prepared_database: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_scope(session_factory) as session:
        repository = JobRepository(session)
        first, created_first = await repository.create(
            job_type=JobType.ANALYZE,
            payload={"a": 1},
            idempotency_key="key-1",
            request_hash="hash-1",
        )
        second, created_second = await repository.create(
            job_type=JobType.ANALYZE,
            payload={"a": 1},
            idempotency_key="key-1",
            request_hash="hash-1",
        )
        assert created_first is True
        assert created_second is False
        assert first.id == second.id


async def test_idempotency_key_conflict_is_reported(
    prepared_database: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_scope(session_factory) as session:
        repository = JobRepository(session)
        await repository.create(
            job_type=JobType.ANALYZE,
            payload={"a": 1},
            idempotency_key="key-1",
            request_hash="hash-1",
        )
        with pytest.raises(ConflictError):
            await repository.create(
                job_type=JobType.ANALYZE,
                payload={"a": 2},
                idempotency_key="key-1",
                request_hash="hash-2",
            )


async def test_stale_running_jobs_return_to_the_queue(
    prepared_database: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    job_id = await _create_job(session_factory)
    queue = JobQueue(session_factory)
    claimed = await queue.claim(worker_id="worker-1")
    assert claimed is not None
    async with session_scope(session_factory) as session:
        repository = JobRepository(session)
        job = await repository.get(job_id)
        assert job is not None
        job.heartbeat_at = utc_now() - timedelta(seconds=600)
    recovered = await queue.recover_stale(stale_after_seconds=300)
    assert recovered == 1
    async with session_scope(session_factory) as session:
        repository = JobRepository(session)
        job = await repository.get(job_id)
        assert job is not None
        assert job.status == JobStatus.QUEUED.value


async def test_worker_executes_a_registered_handler(
    settings: Settings,
    prepared_database: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
    store: LocalObjectStore,
) -> None:
    job_id = await _create_job(session_factory, payload={"seed": 7})
    registry = JobHandlerRegistry()
    executed: list[str] = []

    async def handler(context: JobExecutionContext) -> dict[str, Any]:
        executed.append(context.job_id)
        assert context.seed == 7
        return {"artifact_ids": []}

    registry.register(JobType.ANALYZE, handler)
    worker = Worker(
        settings=settings,
        engine=prepared_database,
        object_store=store,
        registry=registry,
        worker_id="worker-test",
    )
    assert await worker.run_once() is True
    assert executed == [job_id]
    async with session_scope(session_factory) as session:
        repository = JobRepository(session)
        job = await repository.get(job_id)
        assert job is not None
        assert job.status == JobStatus.SUCCEEDED.value
        assert job.result == {"artifact_ids": []}
        assert job.progress == 1.0


async def test_worker_fails_a_job_without_a_registered_handler(
    settings: Settings,
    prepared_database: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
    store: LocalObjectStore,
) -> None:
    job_id = await _create_job(session_factory, job_type=JobType.INGEST)
    worker = Worker(
        settings=settings,
        engine=prepared_database,
        object_store=store,
        registry=JobHandlerRegistry(),
        worker_id="worker-test",
    )
    assert await worker.run_once() is True
    async with session_scope(session_factory) as session:
        repository = JobRepository(session)
        job = await repository.get(job_id)
        assert job is not None
        assert job.status == JobStatus.FAILED.value
        assert job.error is not None
        assert job.error["code"] == "job_error"
        assert "ingest" in job.error["message"]


async def test_worker_skips_a_job_with_cancellation_requested(
    settings: Settings,
    prepared_database: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
    store: LocalObjectStore,
) -> None:
    job_id = await _create_job(session_factory)
    async with session_scope(session_factory) as session:
        repository = JobRepository(session)
        assert await repository.request_cancel(job_id) is True
    registry = JobHandlerRegistry()
    executed: list[str] = []

    async def handler(context: JobExecutionContext) -> dict[str, Any]:
        executed.append(context.job_id)
        return {}

    registry.register(JobType.ANALYZE, handler)
    worker = Worker(
        settings=settings,
        engine=prepared_database,
        object_store=store,
        registry=registry,
        worker_id="worker-test",
    )
    assert await worker.run_once() is True
    assert executed == []
    async with session_scope(session_factory) as session:
        repository = JobRepository(session)
        job = await repository.get(job_id)
        assert job is not None
        assert job.status == JobStatus.CANCELLED.value


async def test_worker_reports_an_empty_queue(
    settings: Settings,
    prepared_database: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
    store: LocalObjectStore,
) -> None:
    worker = Worker(
        settings=settings,
        engine=prepared_database,
        object_store=store,
        registry=JobHandlerRegistry(),
        worker_id="worker-test",
    )
    assert await worker.run_once() is False


async def test_registry_rejects_duplicate_handlers() -> None:
    registry = JobHandlerRegistry()

    async def handler(context: JobExecutionContext) -> dict[str, Any]:
        return {}

    registry.register(JobType.ANALYZE, handler)
    assert registry.supports(JobType.ANALYZE)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(JobType.ANALYZE, handler)


async def test_repository_requires_an_existing_job(
    prepared_database: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from trendsmapp.errors import NotFoundError

    async with session_scope(session_factory) as session:
        repository = JobRepository(session)
        with pytest.raises(NotFoundError):
            await repository.require("job_" + "0" * 32)


async def test_job_rows_store_progress_and_stage(
    prepared_database: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    job_id = await _create_job(session_factory)
    async with session_scope(session_factory) as session:
        repository = JobRepository(session)
        await repository.record_progress(job_id, progress=0.5, stage="interpolation")
    async with session_scope(session_factory) as session:
        repository = JobRepository(session)
        job = await session.get(JobRow, job_id)
        assert job is not None
        assert job.progress == pytest.approx(0.5)
        assert job.stage == "interpolation"
