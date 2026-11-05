"""Job API contract: the read model of the durable job table."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from trendsmapp.contracts.common import JobId, RunId

__all__ = ["CancelJobResponse", "JobResponse", "JobStatusValue"]

JobStatusValue = Literal["queued", "running", "succeeded", "failed", "cancelled"]


class JobResponse(BaseModel):
    """One durable job as seen by a client."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    job_id: JobId
    job_type: str
    status: JobStatusValue
    progress: float = Field(ge=0.0, le=1.0)
    stage: str | None = None
    attempts: int = Field(ge=0)
    cancel_requested: bool = False
    worker_id: str | None = None
    run_id: RunId | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    created_at: datetime
    started_at: datetime | None = None
    heartbeat_at: datetime | None = None
    finished_at: datetime | None = None


class CancelJobResponse(BaseModel):
    """The acknowledgement of a cancellation request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    job_id: JobId
    status: JobStatusValue
    cancel_requested: bool
