"""Dataset and version persistence."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trendsmapp.clock import utc_now
from trendsmapp.errors import NotFoundError
from trendsmapp.persistence.models import DatasetRow, DatasetVersionRow

__all__ = ["DatasetRepository"]


class DatasetRepository:
    """Reads and writes dataset and dataset-version rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_dataset(
        self,
        *,
        dataset_id: str,
        name: str,
        description: str | None = None,
    ) -> DatasetRow:
        """Create a dataset row."""
        now = utc_now()
        row = DatasetRow(
            id=dataset_id,
            name=name,
            description=description,
            created_at=now,
            updated_at=now,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def get_dataset(self, dataset_id: str) -> DatasetRow | None:
        """Return a dataset by identifier."""
        return await self._session.get(DatasetRow, dataset_id)

    async def create_version(
        self,
        *,
        version_id: str,
        dataset_id: str,
        version_number: int,
        schema_version: str,
        normalized_artifact_id: str | None = None,
        normalized_sha256: str | None = None,
        row_count: int = 0,
        parameter_count: int = 0,
        station_count: int = 0,
        first_sampled_at: datetime | None = None,
        last_sampled_at: datetime | None = None,
        boundary_id: str | None = None,
        recipe_id: str | None = None,
    ) -> DatasetVersionRow:
        """Create a dataset-version row."""
        row = DatasetVersionRow(
            id=version_id,
            dataset_id=dataset_id,
            version_number=version_number,
            schema_version=schema_version,
            normalized_artifact_id=normalized_artifact_id,
            normalized_sha256=normalized_sha256,
            row_count=row_count,
            parameter_count=parameter_count,
            station_count=station_count,
            first_sampled_at=first_sampled_at,
            last_sampled_at=last_sampled_at,
            boundary_id=boundary_id,
            recipe_id=recipe_id,
            created_at=utc_now(),
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def seal_version(self, version_id: str) -> DatasetVersionRow:
        """Mark a dataset version as sealed and immutable."""
        row = await self.require_version(version_id)
        row.sealed_at = utc_now()
        dataset = await self._session.get(DatasetRow, row.dataset_id)
        if dataset is not None:
            dataset.current_version_id = version_id
            dataset.updated_at = utc_now()
        await self._session.flush()
        return row

    async def get_version(self, version_id: str) -> DatasetVersionRow | None:
        """Return a dataset version by identifier."""
        return await self._session.get(DatasetVersionRow, version_id)

    async def require_version(self, version_id: str) -> DatasetVersionRow:
        """Return a dataset version, raising when it does not exist."""
        row = await self.get_version(version_id)
        if row is None:
            raise NotFoundError(
                "The requested dataset version does not exist.",
                details={"dataset_version_id": version_id},
            )
        return row

    async def list_versions(self, dataset_id: str) -> list[DatasetVersionRow]:
        """Return every version of a dataset, oldest first."""
        result = await self._session.execute(
            select(DatasetVersionRow)
            .where(DatasetVersionRow.dataset_id == dataset_id)
            .order_by(DatasetVersionRow.version_number)
        )
        return list(result.scalars())

    async def next_version_number(self, dataset_id: str) -> int:
        """Return the next sequential version number for a dataset."""
        versions = await self.list_versions(dataset_id)
        return max((version.version_number for version in versions), default=0) + 1

    async def list_datasets(self, *, limit: int = 100, offset: int = 0) -> list[DatasetRow]:
        """Return datasets, most recently updated first, with a bound."""
        result = await self._session.execute(
            select(DatasetRow)
            .order_by(DatasetRow.updated_at.desc(), DatasetRow.id)
            .limit(min(max(limit, 1), 1000))
            .offset(max(offset, 0))
        )
        return list(result.scalars())

    async def count_datasets(self) -> int:
        """Return the total number of datasets."""
        from sqlalchemy import func

        result = await self._session.execute(select(func.count()).select_from(DatasetRow))
        return int(result.scalar_one())

    async def update_version_stats(
        self,
        version_id: str,
        *,
        row_count: int,
        parameter_count: int,
        station_count: int,
        first_sampled_at: datetime | None,
        last_sampled_at: datetime | None,
        normalized_artifact_id: str | None = None,
        normalized_sha256: str | None = None,
        boundary_id: str | None = None,
    ) -> DatasetVersionRow:
        """Fill in the measured statistics of a dataset version after ingestion."""
        row = await self.require_version(version_id)
        row.row_count = row_count
        row.parameter_count = parameter_count
        row.station_count = station_count
        row.first_sampled_at = first_sampled_at
        row.last_sampled_at = last_sampled_at
        if normalized_artifact_id is not None:
            row.normalized_artifact_id = normalized_artifact_id
        if normalized_sha256 is not None:
            row.normalized_sha256 = normalized_sha256
        if boundary_id is not None:
            row.boundary_id = boundary_id
        await self._session.flush()
        return row
