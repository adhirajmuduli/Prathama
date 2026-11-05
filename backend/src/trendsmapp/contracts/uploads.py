"""Upload API contract: request and response documents.

Every identifier in these documents has a fixed shape (see
:mod:`trendsmapp.contracts.common`), every digest is a lowercase SHA-256, and
every stored byte stream is referenced through an artifact reference rather
than a path. The documents are versioned with the artifact schema version.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from trendsmapp.contracts.common import (
    ArtifactRef,
    DatasetId,
    JobId,
    Sha256Hex,
    UploadId,
)

__all__ = [
    "AbortUploadResponse",
    "CompleteUploadResponse",
    "CreateUploadRequest",
    "PartPlanResponse",
    "PartUploadResponse",
    "UploadSessionResponse",
    "UploadStatusResponse",
]

UploadStatus = Literal["open", "completed", "cancelled"]


class CreateUploadRequest(BaseModel):
    """The body of ``POST /api/v1/uploads``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    filename: str = Field(min_length=1, max_length=255)
    content_type: str | None = Field(default=None, max_length=255)
    size_bytes: int = Field(gt=0)
    sha256: Sha256Hex | None = None
    chunk_size_bytes: int | None = Field(default=None, gt=0)
    dataset_id: DatasetId | None = None


class PartPlanResponse(BaseModel):
    """One planned part of an upload."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    part_number: int = Field(ge=1)
    start_byte: int = Field(ge=0)
    end_byte: int = Field(ge=0)
    size_bytes: int = Field(gt=0)


class UploadSessionResponse(BaseModel):
    """The response of creating an upload session."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    upload_id: UploadId
    filename: str
    extension: str
    size_bytes: int
    chunk_size_bytes: int
    part_count: int
    parts: tuple[PartPlanResponse, ...]
    status: Literal["open"] = "open"
    expires_at: datetime
    created_at: datetime


class UploadStatusResponse(BaseModel):
    """The current state of an upload session."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    upload_id: UploadId
    status: UploadStatus
    filename: str
    extension: str
    size_bytes: int
    sha256: Sha256Hex | None
    parts_received: tuple[int, ...]
    missing_parts: tuple[int, ...]
    artifact: ArtifactRef | None = None
    job_id: JobId | None = None
    expires_at: datetime
    created_at: datetime
    completed_at: datetime | None = None


class PartUploadResponse(BaseModel):
    """The acknowledgement of one stored part."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    upload_id: UploadId
    part_number: int
    size_bytes: int
    sha256: Sha256Hex
    received: Literal[True] = True


class CompleteUploadResponse(BaseModel):
    """The response of completing an upload: the raw artifact and the ingest job."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    upload_id: UploadId
    status: Literal["completed"] = "completed"
    artifact: ArtifactRef
    job_id: JobId


class AbortUploadResponse(BaseModel):
    """The response of aborting an upload session."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    upload_id: UploadId
    status: Literal["cancelled"] = "cancelled"
