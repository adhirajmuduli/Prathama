"""PDF report API contract.

A report is a rendered PDF summary of one succeeded run — cover with hashes,
methods, result tables, embedded figures, the ML section, and a checksum
appendix. The report id is the id stored in its artifact's details, so
``GET /api/v1/reports/{report_id}`` resolves through the artifact row.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from trendsmapp.contracts.common import ArtifactRef, JobId, RunId

__all__ = [
    "CreateReportRequest",
    "CreateReportResponse",
    "ReportId",
    "ReportResponse",
]

ReportId = Annotated[str, StringConstraints(pattern=r"^rpt_[0-9a-f]{32}$")]


class CreateReportRequest(BaseModel):
    """The body of ``POST /api/v1/reports``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: RunId


class CreateReportResponse(BaseModel):
    """The 202 response of creating a report."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    report_id: ReportId
    job_id: JobId
    run_id: RunId
    status: str = "accepted"


class ReportResponse(BaseModel):
    """One report with its PDF artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    report_id: ReportId
    run_id: RunId
    job_id: JobId | None = None
    status: str
    artifact: ArtifactRef
    summary: dict[str, Any] = Field(default_factory=dict)
