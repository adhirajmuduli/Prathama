"""Recipe and run metadata persistence."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trendsmapp.clock import utc_now
from trendsmapp.errors import NotFoundError
from trendsmapp.persistence.models import RunRow

__all__ = ["RunRepository"]


class RunRepository:
    """Reads and writes analysis-run rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        run_id: str,
        dataset_version_id: str,
        recipe_hash: str,
        recipe: dict[str, Any],
        dataset_sha256: str,
        boundary_sha256: str | None,
        seed: int,
        application_version: str,
        schema_version: str,
        job_id: str | None = None,
        status: str = "queued",
    ) -> RunRow:
        """Create a run row."""
        row = RunRow(
            id=run_id,
            dataset_version_id=dataset_version_id,
            job_id=job_id,
            recipe_hash=recipe_hash,
            recipe=recipe,
            dataset_sha256=dataset_sha256,
            boundary_sha256=boundary_sha256,
            seed=seed,
            application_version=application_version,
            schema_version=schema_version,
            status=status,
            created_at=utc_now(),
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def get(self, run_id: str) -> RunRow | None:
        """Return a run by identifier."""
        return await self._session.get(RunRow, run_id)

    async def require(self, run_id: str) -> RunRow:
        """Return a run, raising when it does not exist."""
        row = await self.get(run_id)
        if row is None:
            raise NotFoundError("The requested run does not exist.", details={"run_id": run_id})
        return row

    async def list_for_version(self, dataset_version_id: str) -> list[RunRow]:
        """Return every run of a dataset version, oldest first."""
        result = await self._session.execute(
            select(RunRow)
            .where(RunRow.dataset_version_id == dataset_version_id)
            .order_by(RunRow.created_at, RunRow.id)
        )
        return list(result.scalars())

    async def find_by_recipe(self, dataset_version_id: str, recipe_hash: str) -> RunRow | None:
        """Return the run of a dataset version for a recipe hash, when any.

        The recipe hash is the idempotency key of an analysis: the same recipe
        on the same dataset version is never run twice.
        """
        result = await self._session.execute(
            select(RunRow)
            .where(
                RunRow.dataset_version_id == dataset_version_id,
                RunRow.recipe_hash == recipe_hash,
            )
            .order_by(RunRow.created_at, RunRow.id)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def finish(self, run_id: str, *, status: str) -> RunRow:
        """Mark a run as finished with a terminal status."""
        row = await self.require(run_id)
        row.status = status
        row.finished_at = utc_now()
        await self._session.flush()
        return row
