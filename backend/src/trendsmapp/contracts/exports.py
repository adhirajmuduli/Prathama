"""Export-bundle API contract.

An export is a checksum-verified, self-contained ZIP bundle of one succeeded
run: the run manifest, the methods record, the result tables, and every
artifact the run produced. The bundle id is also the id of its artifact row,
so ``GET /api/v1/exports/{export_id}`` reads the artifact directly.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from trendsmapp.contracts.common import ArtifactRef, JobId, RunId

__all__ = [
    "CreateExportRequest",
    "CreateExportResponse",
    "ExportId",
    "ExportResponse",
]

ExportId = Annotated[str, StringConstraints(pattern=r"^exp_[0-9a-f]{32}$")]


class CreateExportRequest(BaseModel):
    """The body of ``POST /api/v1/exports``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: RunId


class CreateExportResponse(BaseModel):
    """The 202 response of creating an export."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    export_id: ExportId
    job_id: JobId
    run_id: RunId
    status: str = "accepted"


class ExportResponse(BaseModel):
    """One export with its bundle artifact and the manifest inside it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    export_id: ExportId
    run_id: RunId
    job_id: JobId | None = None
    status: str
    artifact: ArtifactRef
    manifest: dict[str, Any] = Field(default_factory=dict)
