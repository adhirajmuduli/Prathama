"""Worker process lifecycle, startup validation, polling loop, and dispatch.

The worker is the only process that performs scientific computation. It
validates its dependencies at startup, then polls the durable job table,
claims one job at a time, and records progress, completion, failure, and
cancellation on that job row.
"""

from __future__ import annotations

import asyncio
import os
import signal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from trendsmapp.domain.enums import JobType
from trendsmapp.errors import JobError, TrendsmappError
from trendsmapp.logging_config import bind_job_context, clear_context, get_logger
from trendsmapp.persistence.database import (
    create_engine_for_settings,
    create_session_factory,
    database_health,
    dispose_engine,
    session_scope,
)
from trendsmapp.persistence.repositories.jobs import JobRepository
from trendsmapp.settings import Settings, get_settings
from trendsmapp.storage.base import ObjectStore
from trendsmapp.storage.factory import create_object_store
from trendsmapp.worker.handlers import JobExecutionContext, JobHandlerRegistry
from trendsmapp.worker.heartbeat import HeartbeatMonitor
from trendsmapp.worker.queue import JobQueue

__all__ = ["Worker", "run_worker"]

logger = get_logger(__name__)


class Worker:
    """The worker process."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        engine: AsyncEngine | None = None,
        object_store: ObjectStore | None = None,
        registry: JobHandlerRegistry | None = None,
        worker_id: str | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._owns_engine = engine is None
        self._engine = engine or create_engine_for_settings(self._settings)
        self._session_factory = create_session_factory(self._engine)
        self._object_store = object_store or create_object_store(self._settings)
        self._registry = registry or JobHandlerRegistry()
        self._worker_id = worker_id or f"worker-{os.getpid()}"
        self._queue = JobQueue(self._session_factory)
        self._heartbeat = HeartbeatMonitor(
            self._session_factory,
            stale_after_seconds=self._settings.worker_stale_after_seconds,
        )
        self._stopping = asyncio.Event()

    @property
    def worker_id(self) -> str:
        """Return the identifier of this worker."""
        return self._worker_id

    @property
    def registry(self) -> JobHandlerRegistry:
        """Return the handler registry used by this worker."""
        return self._registry

    async def startup(self) -> None:
        """Validate the worker's dependencies before it starts polling."""
        if not await database_health(self._engine):
            raise JobError("The worker cannot reach the database.")
        if not self._object_store.ping():
            raise JobError("The worker cannot reach the object store.")
        logger.info(
            "worker_started",
            worker_id=self._worker_id,
            registered_job_types=[item.value for item in self._registry.registered_types],
        )

    async def shutdown(self) -> None:
        """Release the resources owned by the worker."""
        if self._owns_engine:
            await dispose_engine(self._engine)
        logger.info("worker_stopped", worker_id=self._worker_id)

    def request_stop(self) -> None:
        """Ask the polling loop to stop after the current job."""
        self._stopping.set()

    async def run_forever(self) -> None:
        """Poll for jobs until a stop is requested."""
        await self.startup()
        try:
            while not self._stopping.is_set():
                processed = await self.run_once()
                if not processed:
                    try:
                        await asyncio.wait_for(
                            self._stopping.wait(),
                            timeout=self._settings.worker_poll_interval_seconds,
                        )
                    except TimeoutError:
                        continue
        finally:
            await self.shutdown()

    async def run_once(self) -> bool:
        """Claim and execute at most one job.

        Returns whether a job was claimed. A job that fails is recorded as
        failed and does not stop the worker.
        """
        recovered = await self._queue.recover_stale(
            stale_after_seconds=self._settings.worker_stale_after_seconds
        )
        if recovered:
            logger.warning("stale_jobs_requeued", count=recovered)
        job = await self._queue.claim(worker_id=self._worker_id)
        if job is None:
            return False
        await self._execute(job.id, job.job_type, job.payload, job.run_id, job.dataset_version_id)
        return True

    async def _execute(
        self,
        job_id: str,
        job_type: str,
        payload: dict[str, Any],
        run_id: str | None,
        dataset_version_id: str | None,
    ) -> None:
        """Execute one claimed job and record its terminal state."""
        bind_job_context(job_id, run_id)
        try:
            try:
                resolved_type = JobType(job_type)
            except ValueError as exc:
                raise JobError(
                    f"'{job_type}' is not a known job type.",
                    details={"job_type": job_type},
                ) from exc
            if await self._queue.cancel_requested(job_id):
                await self._mark_cancelled(job_id)
                return
            context = JobExecutionContext(
                job_id=job_id,
                job_type=resolved_type,
                payload=dict(payload or {}),
                run_id=run_id,
                dataset_version_id=dataset_version_id,
                seed=int((payload or {}).get("seed", 0)),
                settings=self._settings,
                object_store=self._object_store,
                session_factory=self._session_factory,
                heartbeat=self._heartbeat,
                cancellation_probe=lambda: self._queue.cancel_requested(job_id),
            )
            result = await self._registry.dispatch(context)
            if await self._queue.cancel_requested(job_id):
                await self._mark_cancelled(job_id)
                return
            await self._mark_succeeded(job_id, result)
        except TrendsmappError as exc:
            logger.error("job_failed", job_id=job_id, code=exc.code, message=exc.message)
            await self._mark_failed(job_id, exc.as_payload())
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - a job failure must not kill the worker
            logger.error("job_crashed", job_id=job_id, error_type=type(exc).__name__)
            await self._mark_failed(
                job_id,
                {
                    "code": "internal_error",
                    "message": "The job failed with an unexpected internal error.",
                    "details": {},
                },
            )
        finally:
            clear_context()

    async def _mark_succeeded(self, job_id: str, result: dict[str, Any]) -> None:
        async with session_scope(self._session_factory) as session:
            repository = JobRepository(session)
            await repository.complete(job_id, result)

    async def _mark_failed(self, job_id: str, error: dict[str, Any]) -> None:
        async with session_scope(self._session_factory) as session:
            repository = JobRepository(session)
            await repository.fail(job_id, error)

    async def _mark_cancelled(self, job_id: str) -> None:
        async with session_scope(self._session_factory) as session:
            repository = JobRepository(session)
            await repository.mark_cancelled(job_id)


async def run_worker(
    *,
    settings: Settings | None = None,
    registry: JobHandlerRegistry | None = None,
    signal_handlers: bool = True,
) -> None:
    """Run the worker until it is asked to stop."""
    resolved = settings or get_settings()
    worker = Worker(settings=resolved, registry=registry)
    if signal_handlers:
        _install_signal_handlers(worker)
    await worker.run_forever()


def _install_signal_handlers(worker: Worker) -> None:
    """Ask the worker to stop cleanly on SIGINT and SIGTERM."""
    loop = asyncio.get_running_loop()
    for signal_name in ("SIGINT", "SIGTERM"):
        received = getattr(signal, signal_name, None)
        if received is None:
            continue
        try:
            loop.add_signal_handler(received, worker.request_stop)
        except (NotImplementedError, RuntimeError):  # pragma: no cover - platform dependent
            continue
