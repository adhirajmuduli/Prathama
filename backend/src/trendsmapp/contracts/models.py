"""Model-run API contract.

A model run is the record of one training job: the task that was asked for,
the run that executed it, the results, and the explanations. The documents are
versioned with the task schema and forbid extra fields.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from trendsmapp.contracts.common import ArtifactRef, DatasetVersionId, JobId, RunId
from trendsmapp.contracts.tasks import MLTask

__all__ = [
    "CreateModelRunResponse",
    "ModelRunResponse",
]


class CreateModelRunResponse(BaseModel):
    """The 202 response of creating a model run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: RunId
    job_id: JobId
    task_hash: str = Field(min_length=64, max_length=64)
    status: str = "accepted"


class ModelRunResponse(BaseModel):
    """One model run with its results and explanations."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: RunId
    dataset_version_id: DatasetVersionId
    job_id: JobId | None = None
    status: str
    task: MLTask
    task_hash: str
    created_at: datetime
    finished_at: datetime | None = None
    results: dict[str, Any] | None = None
    explanations: dict[str, Any] | None = None
    artifacts: tuple[ArtifactRef, ...] = ()
    warnings: tuple[str, ...] = ()
