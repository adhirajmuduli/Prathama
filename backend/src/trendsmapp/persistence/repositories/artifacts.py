"""Artifact reference persistence with hash uniqueness."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from trendsmapp.clock import utc_now
from trendsmapp.errors import NotFoundError
from trendsmapp.persistence.models import ArtifactLinkRow, ArtifactRow

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
        """Register an artifact reference, idempotently.

        The same bytes may be registered under several kinds, but the same
        kind and hash pair is unique, which keeps artifact indexes stable.
        Re-registering the same digest and kind returns the row that is
        already stored instead of failing the unique constraint, so uploading
        the same file twice is a no-op, not an error. When ``run_id`` or
        ``dataset_version_id`` is given, the row is additionally linked to
        that owner through ``artifact_links``, so every run lists its own
        artifacts even when the bytes are identical to another run's.
        """
        existing = await self.get_by_digest(kind=kind, sha256=sha256)
        if existing is None:
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
            try:
                await self._session.flush()
            except IntegrityError:
                # Another writer registered the same digest concurrently; the
                # existing row wins and is returned.
                await self._session.rollback()
                existing = await self.get_by_digest(kind=kind, sha256=sha256)
                if existing is None:
                    raise
            else:
                existing = row
        if run_id is not None:
            await self._link(existing.id, "run", run_id)
        if dataset_version_id is not None:
            await self._link(existing.id, "dataset_version", dataset_version_id)
        return existing

    async def _link(self, artifact_id: str, owner_type: str, owner_id: str) -> None:
        """Link an artifact to an owner, idempotently."""
        result = await self._session.execute(
            select(ArtifactLinkRow).where(
                ArtifactLinkRow.artifact_id == artifact_id,
                ArtifactLinkRow.owner_type == owner_type,
                ArtifactLinkRow.owner_id == owner_id,
            )
        )
        if result.scalar_one_or_none() is not None:
            return
        self._session.add(
            ArtifactLinkRow(artifact_id=artifact_id, owner_type=owner_type, owner_id=owner_id)
        )
        try:
            await self._session.flush()
        except IntegrityError:
            await self._session.rollback()

    async def get_by_digest(self, *, kind: str, sha256: str) -> ArtifactRow | None:
        """Return the artifact registered for a digest and kind, when any."""
        result = await self._session.execute(
            select(ArtifactRow).where(ArtifactRow.kind == kind, ArtifactRow.sha256 == sha256)
        )
        return result.scalar_one_or_none()

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

    async def find_by_details(self, kind: str, details_key: str, value: str) -> ArtifactRow | None:
        """Return the artifact of a kind whose details carry a key/value pair."""
        result = await self._session.execute(
            select(ArtifactRow)
            .where(
                ArtifactRow.kind == kind,
                ArtifactRow.details[details_key].as_string() == value,
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def find_by_export_id(self, export_id: str) -> ArtifactRow | None:
        """Return the export bundle registered under an export id, when any."""
        result = await self._session.execute(
            select(ArtifactRow)
            .where(
                ArtifactRow.kind == "export_bundle",
                ArtifactRow.details["export_id"].as_string() == export_id,
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_for_run(self, run_id: str) -> list[ArtifactRow]:
        """Return every artifact linked to a run, including reused bytes."""
        result = await self._session.execute(
            select(ArtifactRow)
            .join(
                ArtifactLinkRow,
                (ArtifactLinkRow.artifact_id == ArtifactRow.id)
                & (ArtifactLinkRow.owner_type == "run")
                & (ArtifactLinkRow.owner_id == run_id),
            )
            .order_by(ArtifactRow.created_at)
        )
        return list(result.scalars().unique())

    async def list_for_version(self, dataset_version_id: str) -> list[ArtifactRow]:
        """Return every artifact linked to a dataset version."""
        result = await self._session.execute(
            select(ArtifactRow)
            .join(
                ArtifactLinkRow,
                (ArtifactLinkRow.artifact_id == ArtifactRow.id)
                & (ArtifactLinkRow.owner_type == "dataset_version")
                & (ArtifactLinkRow.owner_id == dataset_version_id),
            )
            .order_by(ArtifactRow.created_at)
        )
        return list(result.scalars().unique())
