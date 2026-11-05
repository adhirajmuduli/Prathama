"""Provenance event persistence."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trendsmapp.clock import utc_now
from trendsmapp.domain.identifiers import new_provenance_id
from trendsmapp.persistence.models import ProvenanceEventRow

__all__ = ["ProvenanceRepository"]


class ProvenanceRepository:
    """Reads and writes provenance events."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record_event(
        self,
        *,
        event_type: str,
        run_id: str | None = None,
        dataset_version_id: str | None = None,
        input_artifact_ids: list[str] | None = None,
        output_artifact_ids: list[str] | None = None,
        transformations: list[dict[str, Any]] | None = None,
        details: dict[str, Any] | None = None,
        provenance_id: str | None = None,
        occurred_at: datetime | None = None,
    ) -> ProvenanceEventRow:
        """Record one provenance event."""
        row = ProvenanceEventRow(
            id=provenance_id or new_provenance_id(),
            event_type=event_type,
            occurred_at=occurred_at or utc_now(),
            run_id=run_id,
            dataset_version_id=dataset_version_id,
            input_artifact_ids=list(input_artifact_ids or []),
            output_artifact_ids=list(output_artifact_ids or []),
            transformations=list(transformations or []),
            details=dict(details or {}),
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def list_for_version(self, dataset_version_id: str) -> list[ProvenanceEventRow]:
        """Return every provenance event of a dataset version, oldest first."""
        result = await self._session.execute(
            select(ProvenanceEventRow)
            .where(ProvenanceEventRow.dataset_version_id == dataset_version_id)
            .order_by(ProvenanceEventRow.occurred_at, ProvenanceEventRow.id)
        )
        return list(result.scalars())

    async def list_for_run(self, run_id: str) -> list[ProvenanceEventRow]:
        """Return every provenance event of a run, oldest first."""
        result = await self._session.execute(
            select(ProvenanceEventRow)
            .where(ProvenanceEventRow.run_id == run_id)
            .order_by(ProvenanceEventRow.occurred_at, ProvenanceEventRow.id)
        )
        return list(result.scalars())
