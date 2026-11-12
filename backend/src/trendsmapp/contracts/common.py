"""Shared contract primitives: identifiers, hashes, references, pagination.

These types are the vocabulary every other contract builds on. They are
deliberately narrow: an identifier has a prefix and a fixed shape, a digest is
a lowercase hexadecimal SHA-256 string, and every stored artifact is
referenced through an :class:`ArtifactRef` rather than a path.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from trendsmapp.clock import isoformat_z
from trendsmapp.contracts.versions import APPLICATION_VERSION, ARTIFACT_SCHEMA_VERSION

__all__ = [
    "ArtifactRef",
    "ArtifactRefKind",
    "DatasetId",
    "DatasetVersionId",
    "JobId",
    "ObservationId",
    "PageMeta",
    "ParameterId",
    "ProvenanceId",
    "ProvenanceRef",
    "ResultMetadata",
    "RunId",
    "Sha256Hex",
    "StationId",
    "UploadId",
    "Warning",
    "WarningSeverity",
]

Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]

DatasetId = Annotated[str, StringConstraints(pattern=r"^ds_[0-9a-f]{32}$")]
DatasetVersionId = Annotated[str, StringConstraints(pattern=r"^dsv_[0-9a-f]{32}$")]
UploadId = Annotated[str, StringConstraints(pattern=r"^upl_[0-9a-f]{32}$")]
JobId = Annotated[str, StringConstraints(pattern=r"^job_[0-9a-f]{32}$")]
RunId = Annotated[str, StringConstraints(pattern=r"^run_[0-9a-f]{32}$")]
ObservationId = Annotated[str, StringConstraints(pattern=r"^obs_[0-9a-f]{32}$")]
StationId = Annotated[str, StringConstraints(pattern=r"^stn_[0-9a-f]{32}$")]
ParameterId = Annotated[str, StringConstraints(pattern=r"^par_[0-9a-f]{32}$")]
ProvenanceId = Annotated[str, StringConstraints(pattern=r"^prv_[0-9a-f]{32}$")]

ArtifactRefKind = Literal[
    "raw_upload",
    "normalized_dataset",
    "qc_report",
    "parse_report",
    "normalization_report",
    "provenance",
    "raster",
    "figure",
    "video",
    "model",
    "metrics",
    "predictions",
    "explanations",
    "export_bundle",
    "report",
    "boundary",
    "other",
]

WarningSeverity = Literal["info", "warning", "error"]


class ArtifactRef(BaseModel):
    """A reference to one immutable stored artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_id: str = Field(pattern=r"^art_[0-9a-f]{32}$")
    kind: ArtifactRefKind
    sha256: Sha256Hex
    size_bytes: int = Field(ge=0)
    content_type: str
    schema_version: str = ARTIFACT_SCHEMA_VERSION
    created_at: datetime
    media_type_detail: dict[str, Any] = Field(default_factory=dict)

    @property
    def created_at_iso(self) -> str:
        """Return the creation timestamp as an RFC 3339 UTC string."""
        return isoformat_z(self.created_at)


class ProvenanceRef(BaseModel):
    """A reference to one provenance event."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provenance_id: ProvenanceId
    event_type: str
    occurred_at: datetime
    parent_artifact_ids: tuple[str, ...] = ()
    transformations: tuple[str, ...] = ()


class Warning(BaseModel):
    """A machine-readable warning attached to a result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    message: str
    severity: WarningSeverity = "warning"
    details: dict[str, Any] = Field(default_factory=dict)


class PageMeta(BaseModel):
    """Pagination metadata for a table response."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=10_000)
    total: int = Field(default=0, ge=0)

    @property
    def has_more(self) -> bool:
        """Return whether another page follows this one."""
        return self.offset + self.limit < self.total


class ResultMetadata(BaseModel):
    """Metadata embedded in every stored result document."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = ARTIFACT_SCHEMA_VERSION
    application_version: str = APPLICATION_VERSION
    run_id: RunId
    generated_at: datetime
