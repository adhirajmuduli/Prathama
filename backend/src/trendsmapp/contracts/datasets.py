"""Dataset API contract: datasets, versions, probe, and preview documents."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from trendsmapp.contracts.common import (
    ArtifactRef,
    DatasetId,
    DatasetVersionId,
    JobId,
    ProvenanceRef,
    Sha256Hex,
    UploadId,
)
from trendsmapp.ingestion.column_mapping import ColumnMapping

__all__ = [
    "CreateDatasetRequest",
    "CreateDatasetResponse",
    "DatasetResponse",
    "DatasetVersionListResponse",
    "DatasetVersionResponse",
    "PreviewResponse",
    "ProbeResponse",
    "ProvenanceListResponse",
    "ReportKind",
]

ReportKind = Literal["parse", "normalization", "qc"]


class CreateDatasetRequest(BaseModel):
    """The body of ``POST /api/v1/datasets``: an upload plus its confirmed mapping."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    upload_id: UploadId
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4096)
    mapping: ColumnMapping


class CreateDatasetResponse(BaseModel):
    """The 202 response of creating a dataset version and its ingest job."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_id: DatasetId
    version_id: DatasetVersionId
    job_id: JobId
    status: Literal["accepted"] = "accepted"


class DatasetResponse(BaseModel):
    """One dataset with its current version."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_id: DatasetId
    name: str
    description: str | None
    current_version_id: DatasetVersionId | None
    created_at: datetime
    updated_at: datetime


class DatasetVersionResponse(BaseModel):
    """One dataset version with its artifacts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version_id: DatasetVersionId
    dataset_id: DatasetId
    version_number: int
    schema_version: str
    sealed: bool
    row_count: int
    parameter_count: int
    station_count: int
    first_sampled_at: datetime | None
    last_sampled_at: datetime | None
    boundary_id: str | None
    normalized_artifact: ArtifactRef | None
    artifacts: tuple[ArtifactRef, ...]
    created_at: datetime
    sealed_at: datetime | None


class DatasetVersionListResponse(BaseModel):
    """The versions of one dataset."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_id: DatasetId
    items: tuple[DatasetVersionResponse, ...]


class ProbeResponse(BaseModel):
    """What the first rows of an upload look like, with a proposed mapping."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    upload_id: UploadId
    filename: str
    extension: str
    file_format: str
    content_type: str | None
    encoding: str | None
    delimiter: str | None
    has_header: bool
    fields: tuple[str, ...]
    decimal_style: str
    layout: str
    layout_confidence: float
    layout_evidence: tuple[str, ...]
    layout_warnings: tuple[str, ...]
    sniff_warnings: tuple[str, ...]
    sheet_names: tuple[str, ...]
    numeric_fields: frozenset[str]
    date_fields: frozenset[str]
    proposed_mapping: ColumnMapping
    proposal_warnings: tuple[str, ...]


class PreviewResponse(BaseModel):
    """The first rows of a normalized dataset version."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version_id: DatasetVersionId
    artifact_sha256: Sha256Hex
    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    row_count: int
    limit: int


class ProvenanceListResponse(BaseModel):
    """The provenance events of a dataset version."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version_id: DatasetVersionId
    items: tuple[ProvenanceRef, ...]
