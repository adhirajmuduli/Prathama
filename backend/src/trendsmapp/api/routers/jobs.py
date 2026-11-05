"""Job read and cancellation endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from trendsmapp.api.dependencies import get_job_repository
from trendsmapp.contracts.jobs import CancelJobResponse, JobResponse
from trendsmapp.persistence.models import JobRow
from trendsmapp.persistence.repositories.jobs import JobRepository

__all__ = ["router"]

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])

_STATUS_MAP = {
    "queued": "queued",
    "running": "running",
    "succeeded": "succeeded",
    "failed": "failed",
    "cancelled": "cancelled",
}


def _to_response(row: JobRow) -> JobResponse:
    """Build the contract response of one job row."""
    return JobResponse(
        job_id=row.id,
        job_type=row.job_type,
        status=_STATUS_MAP.get(row.status, row.status),
        progress=row.progress,
        stage=row.stage,
        attempts=row.attempts,
        cancel_requested=row.cancel_requested,
        worker_id=row.worker_id,
        run_id=row.run_id,
        payload=dict(row.payload or {}),
        result=row.result,
        error=row.error,
        created_at=row.created_at,
        started_at=row.started_at,
        heartbeat_at=row.heartbeat_at,
        finished_at=row.finished_at,
    )


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: str,
    repository: Annotated[JobRepository, Depends(get_job_repository)],
) -> JobResponse:
    """Return one job by identifier."""
    return _to_response(await repository.require(job_id))


@router.post(
    "/{job_id}/cancel", response_model=CancelJobResponse, status_code=status.HTTP_202_ACCEPTED
)
async def cancel_job(
    job_id: str,
    repository: Annotated[JobRepository, Depends(get_job_repository)],
) -> CancelJobResponse:
    """Request cancellation of a queued or running job."""
    await repository.require(job_id)
    requested = await repository.request_cancel(job_id)
    refreshed = await repository.require(job_id)
    return CancelJobResponse(
        job_id=refreshed.id,
        status=_STATUS_MAP.get(refreshed.status, refreshed.status),
        cancel_requested=requested or refreshed.cancel_requested,
    )
