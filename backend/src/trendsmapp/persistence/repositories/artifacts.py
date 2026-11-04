"""Artifact reference persistence with hash uniqueness."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trendsmapp.clock import utc_now
from trendsmapp.errors import NotFoundError
from trendsmapp.persistence.models import ArtifactRow

__all__ = ["ArtifactRepository"]


class ArtifactRepository:
    """Reads and writes artifact-reference rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def register(
        self,
        *,
        artifact_id: str,
        kind: str,
        sha256: str,
        size_bytes: int,
        content_type: str,
        storage_key: str,
        schema_version: str,
        dataset_version_id: str | None = None,
        run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        created_at: datetime | None = None,
    ) -> ArtifactRow:
        """Register an artifact reference.

        The same bytes may be registered under several kinds, but the same
        kind and hash pair is unique, which keeps artifact indexes stable.
        """
        row = ArtifactRow(
            id=artifact_id,
            kind=kind,
            sha256=sha256,
            size_bytes=size_bytes,
            content_type=content_type,
            storage_key=storage_key,
            schema_version=schema_version,
            dataset_version_id=dataset_version_id,
            run_id=run_id,
            details=dict(metadata or {}),
            created_at=created_at or utc_now(),
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def get(self, artifact_id: str) -> ArtifactRow | None:
        """Return an artifact reference by identifier."""
        return await self._session.get(ArtifactRow, artifact_id)

    async def require(self, artifact_id: str) -> ArtifactRow:
        """Return an artifact reference, raising when it does not exist."""
        row = await self.get(artifact_id)
        if row is None:
            raise NotFoundError(
                "The requested artifact does not exist.", details={"artifact_id": artifact_id}
            )
        return row

    async def list_for_run(self, run_id: str) -> list[ArtifactRow]:
        """Return every artifact produced by a run."""
        result = await self._session.execute(
            select(ArtifactRow).where(ArtifactRow.run_id == run_id).order_by(ArtifactRow.created_at)
        )
        return list(result.scalars())

    async def list_for_version(self, dataset_version_id: str) -> list[ArtifactRow]:
        """Return every artifact produced for a dataset version."""
        result = await self._session.execute(
            select(ArtifactRow)
            .where(ArtifactRow.dataset_version_id == dataset_version_id)
            .order_by(ArtifactRow.created_at)
        )
        return list(result.scalars())
