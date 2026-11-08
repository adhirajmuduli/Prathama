"""SQLAlchemy ORM tables.

This module contains tables only. It is never imported by frontend-facing
contracts, and repositories translate ORM rows into the domain models that
carry the scientific meaning.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

__all__ = [
    "ArtifactLinkRow",
    "ArtifactRow",
    "Base",
    "CompatibilityRow",
    "DatasetRow",
    "DatasetVersionRow",
    "JobRow",
    "MethodRow",
    "ParameterRow",
    "ProvenanceEventRow",
    "QcRuleRow",
    "RunRow",
    "StationRow",
    "UploadPartRow",
    "UploadRow",
]

JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


class Base(DeclarativeBase):
    """The declarative base for every Trendsmapp table."""


class DatasetRow(Base):
    """A dataset: the logical collection of uploads and versions."""

    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    current_version_id: Mapped[str | None] = mapped_column(String(64))


class DatasetVersionRow(Base):
    """An immutable, sealed version of a normalized dataset."""

    __tablename__ = "dataset_versions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    normalized_artifact_id: Mapped[str | None] = mapped_column(String(64))
    normalized_sha256: Mapped[str | None] = mapped_column(String(64))
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parameter_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    station_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_sampled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sampled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    boundary_id: Mapped[str | None] = mapped_column(String(64))
    recipe_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("dataset_id", "version_number", name="uix_dataset_version_number"),
        Index("ix_dataset_versions_dataset_id", "dataset_id"),
    )


class UploadRow(Base):
    """A chunked upload session."""

    __tablename__ = "uploads"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(255))
    extension: Mapped[str] = mapped_column(String(16), nullable=False)
    total_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    chunk_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    expected_sha256: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    dataset_id: Mapped[str | None] = mapped_column(String(64))
    raw_artifact_id: Mapped[str | None] = mapped_column(String(64))
    ingest_job_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_uploads_status", "status"),
        Index("ix_uploads_raw_artifact_id", "raw_artifact_id"),
    )


class UploadPartRow(Base):
    """One uploaded part of a chunked upload session."""

    __tablename__ = "upload_parts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    upload_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("uploads.id", ondelete="CASCADE"), nullable=False
    )
    part_number: Mapped[int] = mapped_column(Integer, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("upload_id", "part_number", name="uix_upload_part_number"),
        Index("ix_upload_parts_upload_id", "upload_id"),
    )


class JobRow(Base):
    """A durable unit of scientific work."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE)
    idempotency_key: Mapped[str | None] = mapped_column(String(255))
    request_hash: Mapped[str | None] = mapped_column(String(64))
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    stage: Mapped[str | None] = mapped_column(String(64))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    worker_id: Mapped[str | None] = mapped_column(String(128))
    run_id: Mapped[str | None] = mapped_column(String(64))
    dataset_version_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uix_job_idempotency_key"),
        Index("ix_jobs_status_created_at", "status", "created_at"),
    )


class RunRow(Base):
    """One analysis execution."""

    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dataset_version_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("dataset_versions.id", ondelete="RESTRICT"), nullable=False
    )
    job_id: Mapped[str | None] = mapped_column(String(64))
    recipe_id: Mapped[str | None] = mapped_column(String(64))
    recipe_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    recipe: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    dataset_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    boundary_sha256: Mapped[str | None] = mapped_column(String(64))
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    application_version: Mapped[str] = mapped_column(String(32), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_runs_dataset_version_id", "dataset_version_id"),)


class ArtifactRow(Base):
    """Metadata for one immutable stored artifact."""

    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    dataset_version_id: Mapped[str | None] = mapped_column(String(64))
    run_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON_TYPE, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("sha256", "kind", name="uix_artifact_sha256_kind"),
        Index("ix_artifacts_run_id", "run_id"),
    )


class ArtifactLinkRow(Base):
    """Ownership link between a content-addressed artifact and its owner.

    Artifact rows are unique per (kind, sha256): identical bytes are stored
    once. Ownership — which run or dataset version produced the bytes — is
    many-to-many through this table, so a re-run that reproduces identical
    bytes still lists its own artifacts.
    """

    __tablename__ = "artifact_links"

    artifact_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("artifacts.id", ondelete="CASCADE"), primary_key=True
    )

    #: ``"run"`` or ``"dataset_version"``.
    owner_type: Mapped[str] = mapped_column(String(16), primary_key=True)

    owner_id: Mapped[str] = mapped_column(String(64), primary_key=True)

    __table_args__ = (Index("ix_artifact_links_owner", "owner_type", "owner_id"),)


class ProvenanceEventRow(Base):
    """One provenance event linking inputs to outputs."""

    __tablename__ = "provenance_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    run_id: Mapped[str | None] = mapped_column(String(64))
    dataset_version_id: Mapped[str | None] = mapped_column(String(64))
    input_artifact_ids: Mapped[list[str]] = mapped_column(JSON_TYPE, nullable=False, default=list)
    output_artifact_ids: Mapped[list[str]] = mapped_column(JSON_TYPE, nullable=False, default=list)
    transformations: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_TYPE, nullable=False, default=list
    )
    details: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False, default=dict)

    __table_args__ = (Index("ix_provenance_events_run_id", "run_id"),)


class StationRow(Base):
    """A monitoring station registered for a dataset version."""

    __tablename__ = "stations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dataset_version_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("dataset_versions.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str | None] = mapped_column(String(255))
    latitude_wgs84: Mapped[float] = mapped_column(Float, nullable=False)
    longitude_wgs84: Mapped[float] = mapped_column(Float, nullable=False)
    x_projected_m: Mapped[float | None] = mapped_column(Float)
    y_projected_m: Mapped[float | None] = mapped_column(Float)
    source_crs: Mapped[str] = mapped_column(String(64), nullable=False)
    analysis_crs: Mapped[str] = mapped_column(String(64), nullable=False)
    sector: Mapped[str | None] = mapped_column(String(128))
    first_sampled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sampled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("dataset_version_id", "id", name="uix_station_dataset_version"),
        Index("ix_stations_dataset_version_id", "dataset_version_id"),
    )


class ParameterRow(Base):
    """A measured parameter registered for a dataset version."""

    __tablename__ = "parameters"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dataset_version_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("dataset_versions.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    canonical_unit: Mapped[str | None] = mapped_column(String(64))
    dimension: Mapped[str | None] = mapped_column(String(64))
    display_name: Mapped[str | None] = mapped_column(String(255))
    aliases: Mapped[list[str]] = mapped_column(JSON_TYPE, nullable=False, default=list)
    physical_range_min: Mapped[float | None] = mapped_column(Float)
    physical_range_max: Mapped[float | None] = mapped_column(Float)

    __table_args__ = (Index("ix_parameters_dataset_version_id", "dataset_version_id"),)


class QcRuleRow(Base):
    """A versioned quality-control rule definition."""

    __tablename__ = "qc_rules"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str | None] = mapped_column(String(512))
    applicability: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (UniqueConstraint("code", "version", name="uix_qc_rule_code_version"),)


class MethodRow(Base):
    """A registered measurement method."""

    __tablename__ = "methods"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    reference: Mapped[str | None] = mapped_column(String(512))


class CompatibilityRow(Base):
    """The contract versions this deployment supports."""

    __tablename__ = "contract_compatibility"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    api_major: Mapped[int] = mapped_column(Integer, nullable=False)
    artifact_schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    recipe_schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    application_version: Mapped[str] = mapped_column(String(32), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "api_major",
            "artifact_schema_version",
            "recipe_schema_version",
            name="uix_contract_compatibility",
        ),
    )
