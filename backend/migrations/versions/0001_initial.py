"""Initial schema for metadata, jobs, registries, runs, and artifacts.

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the initial schema."""
    op.create_table(
        "datasets",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current_version_id", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "dataset_versions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("dataset_id", sa.String(length=64), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("normalized_artifact_id", sa.String(length=64), nullable=True),
        sa.Column("normalized_sha256", sa.String(length=64), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("parameter_count", sa.Integer(), nullable=False),
        sa.Column("station_count", sa.Integer(), nullable=False),
        sa.Column("first_sampled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sampled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("boundary_id", sa.String(length=64), nullable=True),
        sa.Column("recipe_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dataset_id", "version_number", name="uix_dataset_version_number"),
    )
    op.create_index("ix_dataset_versions_dataset_id", "dataset_versions", ["dataset_id"])

    op.create_table(
        "uploads",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("extension", sa.String(length=16), nullable=False),
        sa.Column("total_bytes", sa.BigInteger(), nullable=False),
        sa.Column("chunk_size_bytes", sa.Integer(), nullable=False),
        sa.Column("expected_sha256", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("dataset_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_uploads_status", "uploads", ["status"])

    op.create_table(
        "upload_parts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("upload_id", sa.String(length=64), nullable=False),
        sa.Column("part_number", sa.Integer(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["upload_id"], ["uploads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("upload_id", "part_number", name="uix_upload_part_number"),
    )
    op.create_index("ix_upload_parts_upload_id", "upload_parts", ["upload_id"])

    op.create_table(
        "jobs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("job_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("request_hash", sa.String(length=64), nullable=True),
        sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("stage", sa.String(length=64), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(length=128), nullable=True),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("dataset_version_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uix_job_idempotency_key"),
    )
    op.create_index("ix_jobs_status_created_at", "jobs", ["status", "created_at"])

    op.create_table(
        "runs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("dataset_version_id", sa.String(length=64), nullable=False),
        sa.Column("job_id", sa.String(length=64), nullable=True),
        sa.Column("recipe_id", sa.String(length=64), nullable=True),
        sa.Column("recipe_hash", sa.String(length=64), nullable=False),
        sa.Column("recipe", sa.JSON(), nullable=False),
        sa.Column("dataset_sha256", sa.String(length=64), nullable=False),
        sa.Column("boundary_sha256", sa.String(length=64), nullable=True),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("application_version", sa.String(length=32), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["dataset_version_id"], ["dataset_versions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_runs_dataset_version_id", "runs", ["dataset_version_id"])

    op.create_table(
        "artifacts",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("dataset_version_id", sa.String(length=64), nullable=True),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sha256", "kind", name="uix_artifact_sha256_kind"),
    )
    op.create_index("ix_artifacts_run_id", "artifacts", ["run_id"])

    op.create_table(
        "provenance_events",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("dataset_version_id", sa.String(length=64), nullable=True),
        sa.Column("input_artifact_ids", sa.JSON(), nullable=False),
        sa.Column("output_artifact_ids", sa.JSON(), nullable=False),
        sa.Column("transformations", sa.JSON(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_provenance_events_run_id", "provenance_events", ["run_id"])

    op.create_table(
        "stations",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("dataset_version_id", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=True),
        sa.Column("latitude_wgs84", sa.Float(), nullable=False),
        sa.Column("longitude_wgs84", sa.Float(), nullable=False),
        sa.Column("x_projected_m", sa.Float(), nullable=True),
        sa.Column("y_projected_m", sa.Float(), nullable=True),
        sa.Column("source_crs", sa.String(length=64), nullable=False),
        sa.Column("analysis_crs", sa.String(length=64), nullable=False),
        sa.Column("sector", sa.String(length=128), nullable=True),
        sa.Column("first_sampled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sampled_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["dataset_version_id"], ["dataset_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dataset_version_id", "id", name="uix_station_dataset_version"),
    )
    op.create_index("ix_stations_dataset_version_id", "stations", ["dataset_version_id"])

    op.create_table(
        "parameters",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("dataset_version_id", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("canonical_unit", sa.String(length=64), nullable=True),
        sa.Column("dimension", sa.String(length=64), nullable=True),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("aliases", sa.JSON(), nullable=False),
        sa.Column("physical_range_min", sa.Float(), nullable=True),
        sa.Column("physical_range_max", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["dataset_version_id"], ["dataset_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_parameters_dataset_version_id", "parameters", ["dataset_version_id"])

    op.create_table(
        "qc_rules",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=512), nullable=True),
        sa.Column("applicability", sa.JSON(), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", "version", name="uix_qc_rule_code_version"),
    )

    op.create_table(
        "methods",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("reference", sa.String(length=512), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "contract_compatibility",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("api_major", sa.Integer(), nullable=False),
        sa.Column("artifact_schema_version", sa.String(length=32), nullable=False),
        sa.Column("recipe_schema_version", sa.String(length=32), nullable=False),
        sa.Column("application_version", sa.String(length=32), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "api_major",
            "artifact_schema_version",
            "recipe_schema_version",
            name="uix_contract_compatibility",
        ),
    )


def downgrade() -> None:
    """Drop the initial schema."""
    op.drop_table("contract_compatibility")
    op.drop_table("methods")
    op.drop_table("qc_rules")
    op.drop_index("ix_parameters_dataset_version_id", table_name="parameters")
    op.drop_table("parameters")
    op.drop_index("ix_stations_dataset_version_id", table_name="stations")
    op.drop_table("stations")
    op.drop_index("ix_provenance_events_run_id", table_name="provenance_events")
    op.drop_table("provenance_events")
    op.drop_index("ix_artifacts_run_id", table_name="artifacts")
    op.drop_table("artifacts")
    op.drop_index("ix_runs_dataset_version_id", table_name="runs")
    op.drop_table("runs")
    op.drop_index("ix_jobs_status_created_at", table_name="jobs")
    op.drop_table("jobs")
    op.drop_index("ix_upload_parts_upload_id", table_name="upload_parts")
    op.drop_table("upload_parts")
    op.drop_index("ix_uploads_status", table_name="uploads")
    op.drop_table("uploads")
    op.drop_index("ix_dataset_versions_dataset_id", table_name="dataset_versions")
    op.drop_table("dataset_versions")
    op.drop_table("datasets")
