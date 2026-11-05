"""Add the raw artifact and ingest job references to upload sessions.

An upload session, once completed, owns exactly one immutable raw artifact and
one ingest job. Storing both as columns keeps status reads indexed and avoids
querying JSON payloads, which is not portable across database dialects.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_upload_result_columns"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the result columns to the uploads table."""
    op.add_column(
        "uploads",
        sa.Column("raw_artifact_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "uploads",
        sa.Column("ingest_job_id", sa.String(length=64), nullable=True),
    )
    op.create_index("ix_uploads_raw_artifact_id", "uploads", ["raw_artifact_id"])


def downgrade() -> None:
    """Remove the result columns from the uploads table."""
    op.drop_index("ix_uploads_raw_artifact_id", table_name="uploads")
    op.drop_column("uploads", "ingest_job_id")
    op.drop_column("uploads", "raw_artifact_id")
