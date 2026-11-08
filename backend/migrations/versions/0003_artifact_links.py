"""Add the artifact ownership link table.

Artifact rows stay unique per (kind, sha256) — identical bytes are stored
once — but ownership (which run or dataset version produced them) becomes a
many-to-many link. Previously the owner lived in columns on the artifact row,
so re-registering identical bytes from a new run silently kept the old
owner and the new run listed no artifacts of its own.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_artifact_links"
down_revision = "0002_upload_result_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create artifact_links and backfill it from the existing owner columns."""
    op.create_table(
        "artifact_links",
        sa.Column("artifact_id", sa.String(length=64), nullable=False),
        sa.Column("owner_type", sa.String(length=16), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("artifact_id", "owner_type", "owner_id"),
    )
    op.create_index(
        "ix_artifact_links_owner", "artifact_links", ["owner_type", "owner_id"]
    )
    op.execute(
        "INSERT INTO artifact_links (artifact_id, owner_type, owner_id) "
        "SELECT id, 'run', run_id FROM artifacts WHERE run_id IS NOT NULL "
        "ON CONFLICT DO NOTHING"
    )
    op.execute(
        "INSERT INTO artifact_links (artifact_id, owner_type, owner_id) "
        "SELECT id, 'dataset_version', dataset_version_id FROM artifacts "
        "WHERE dataset_version_id IS NOT NULL "
        "ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    """Drop the link table; owner columns on artifacts remain populated."""
    op.drop_index("ix_artifact_links_owner", table_name="artifact_links")
    op.drop_table("artifact_links")
