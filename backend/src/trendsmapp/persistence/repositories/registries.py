"""Parameter, method, station, rule, and compatibility registry access."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trendsmapp.clock import utc_now
from trendsmapp.persistence.models import (
    CompatibilityRow,
    MethodRow,
    ParameterRow,
    QcRuleRow,
    StationRow,
)

__all__ = ["RegistryRepository"]


class RegistryRepository:
    """Reads and writes registry rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_station(
        self,
        *,
        station_id: str,
        dataset_version_id: str,
        label: str | None,
        latitude_wgs84: float,
        longitude_wgs84: float,
        x_projected_m: float | None,
        y_projected_m: float | None,
        source_crs: str,
        analysis_crs: str,
        sector: str | None,
        first_sampled_at: datetime | None = None,
        last_sampled_at: datetime | None = None,
    ) -> StationRow:
        """Register a station for a dataset version."""
        row = StationRow(
            id=station_id,
            dataset_version_id=dataset_version_id,
            label=label,
            latitude_wgs84=latitude_wgs84,
            longitude_wgs84=longitude_wgs84,
            x_projected_m=x_projected_m,
            y_projected_m=y_projected_m,
            source_crs=source_crs,
            analysis_crs=analysis_crs,
            sector=sector,
            first_sampled_at=first_sampled_at,
            last_sampled_at=last_sampled_at,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def list_stations(self, dataset_version_id: str) -> list[StationRow]:
        """Return every station registered for a dataset version."""
        result = await self._session.execute(
            select(StationRow).where(StationRow.dataset_version_id == dataset_version_id)
        )
        return list(result.scalars())

    async def add_parameter(
        self,
        *,
        parameter_id: str,
        dataset_version_id: str,
        label: str,
        canonical_unit: str | None,
        dimension: str | None,
        display_name: str | None = None,
        aliases: list[str] | None = None,
        physical_range_min: float | None = None,
        physical_range_max: float | None = None,
    ) -> ParameterRow:
        """Register a parameter for a dataset version."""
        row = ParameterRow(
            id=parameter_id,
            dataset_version_id=dataset_version_id,
            label=label,
            canonical_unit=canonical_unit,
            dimension=dimension,
            display_name=display_name,
            aliases=list(aliases or []),
            physical_range_min=physical_range_min,
            physical_range_max=physical_range_max,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def list_parameters(self, dataset_version_id: str) -> list[ParameterRow]:
        """Return every parameter registered for a dataset version."""
        result = await self._session.execute(
            select(ParameterRow).where(ParameterRow.dataset_version_id == dataset_version_id)
        )
        return list(result.scalars())

    async def upsert_qc_rule(
        self,
        *,
        rule_id: str,
        code: str,
        severity: str,
        description: str,
        version: str,
        source: str | None = None,
        applicability: dict[str, Any] | None = None,
        enabled: bool = True,
    ) -> QcRuleRow:
        """Insert a quality-control rule, replacing an earlier version of it."""
        result = await self._session.execute(
            select(QcRuleRow).where(QcRuleRow.code == code, QcRuleRow.version == version)
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            existing.severity = severity
            existing.description = description
            existing.source = source
            existing.applicability = dict(applicability or {})
            existing.enabled = enabled
            await self._session.flush()
            return existing
        row = QcRuleRow(
            id=rule_id,
            code=code,
            severity=severity,
            description=description,
            version=version,
            source=source,
            applicability=dict(applicability or {}),
            enabled=enabled,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def list_qc_rules(self, *, enabled_only: bool = True) -> list[QcRuleRow]:
        """Return the registered quality-control rules."""
        statement = select(QcRuleRow).order_by(QcRuleRow.code, QcRuleRow.version)
        if enabled_only:
            statement = statement.where(QcRuleRow.enabled.is_(True))
        result = await self._session.execute(statement)
        return list(result.scalars())

    async def upsert_method(
        self,
        *,
        method_id: str,
        label: str,
        description: str | None = None,
        reference: str | None = None,
    ) -> MethodRow:
        """Insert or update a measurement method."""
        row = await self._session.get(MethodRow, method_id)
        if row is None:
            row = MethodRow(id=method_id, label=label, description=description, reference=reference)
            self._session.add(row)
        else:
            row.label = label
            row.description = description
            row.reference = reference
        await self._session.flush()
        return row

    async def list_methods(self) -> list[MethodRow]:
        """Return every registered method."""
        result = await self._session.execute(select(MethodRow).order_by(MethodRow.label))
        return list(result.scalars())

    async def record_compatibility(
        self,
        *,
        api_major: int,
        artifact_schema_version: str,
        recipe_schema_version: str,
        application_version: str,
    ) -> CompatibilityRow:
        """Record the contract versions this deployment supports."""
        result = await self._session.execute(
            select(CompatibilityRow).where(
                CompatibilityRow.api_major == api_major,
                CompatibilityRow.artifact_schema_version == artifact_schema_version,
                CompatibilityRow.recipe_schema_version == recipe_schema_version,
            )
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            existing.application_version = application_version
            existing.recorded_at = utc_now()
            await self._session.flush()
            return existing
        row = CompatibilityRow(
            api_major=api_major,
            artifact_schema_version=artifact_schema_version,
            recipe_schema_version=recipe_schema_version,
            application_version=application_version,
            recorded_at=utc_now(),
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def list_compatibility(self) -> list[CompatibilityRow]:
        """Return every recorded compatibility record."""
        result = await self._session.execute(
            select(CompatibilityRow).order_by(CompatibilityRow.recorded_at)
        )
        return list(result.scalars())
