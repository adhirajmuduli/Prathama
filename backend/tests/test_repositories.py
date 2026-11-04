"""Repository tests for datasets, uploads, runs, artifacts, and registries."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from trendsmapp.domain.identifiers import (
    new_artifact_id,
    new_dataset_id,
    new_dataset_version_id,
    new_parameter_id,
    new_run_id,
    new_station_id,
    new_upload_id,
)
from trendsmapp.errors import ConflictError, NotFoundError
from trendsmapp.persistence.repositories.artifacts import ArtifactRepository
from trendsmapp.persistence.repositories.datasets import DatasetRepository
from trendsmapp.persistence.repositories.registries import RegistryRepository
from trendsmapp.persistence.repositories.runs import RunRepository
from trendsmapp.persistence.repositories.uploads import UploadRepository

pytestmark = pytest.mark.usefixtures("prepared_database")


async def _seed_dataset_version(
    session: AsyncSession,
) -> tuple[str, str]:
    """Create a dataset with one version and return both identifiers."""
    datasets = DatasetRepository(session)
    dataset_id = new_dataset_id()
    version_id = new_dataset_version_id()
    await datasets.create_dataset(dataset_id=dataset_id, name="Chilika observations")
    await datasets.create_version(
        version_id=version_id,
        dataset_id=dataset_id,
        version_number=1,
        schema_version="1.0.0",
        row_count=12,
        parameter_count=2,
        station_count=3,
    )
    return dataset_id, version_id


async def test_dataset_repository_creates_versions_and_numbers_them(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        repository = DatasetRepository(session)
        dataset_id = new_dataset_id()
        await repository.create_dataset(
            dataset_id=dataset_id,
            name="Chilika observations",
            description="Field campaign",
        )
        stored = await repository.get_dataset(dataset_id)
        assert stored is not None
        assert stored.name == "Chilika observations"
        assert stored.description == "Field campaign"
        assert await repository.get_dataset("ds_missing") is None

        first = new_dataset_version_id()
        second = new_dataset_version_id()
        await repository.create_version(
            version_id=first,
            dataset_id=dataset_id,
            version_number=1,
            schema_version="1.0.0",
        )
        await repository.create_version(
            version_id=second,
            dataset_id=dataset_id,
            version_number=2,
            schema_version="1.0.0",
        )
        versions = await repository.list_versions(dataset_id)
        assert [version.id for version in versions] == [first, second]
        assert await repository.next_version_number(dataset_id) == 3
        await session.commit()

    async with session_factory() as session:
        repository = DatasetRepository(session)
        assert await repository.next_version_number(new_dataset_id()) == 1


async def test_dataset_repository_seals_a_version_and_points_the_dataset_at_it(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        repository = DatasetRepository(session)
        dataset_id, version_id = await _seed_dataset_version(session)
        sealed = await repository.seal_version(version_id)
        assert sealed.sealed_at is not None
        dataset = await repository.get_dataset(dataset_id)
        assert dataset is not None
        assert dataset.current_version_id == version_id
        await session.commit()

    async with session_factory() as session:
        repository = DatasetRepository(session)
        with pytest.raises(NotFoundError):
            await repository.require_version(new_dataset_version_id())


async def test_upload_repository_tracks_parts_and_rejects_invalid_transitions(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        repository = UploadRepository(session)
        upload_id = new_upload_id()
        created = await repository.create_session(
            upload_id=upload_id,
            filename="observations.csv",
            extension=".csv",
            content_type="text/csv",
            total_bytes=12,
            chunk_size_bytes=5,
            expected_sha256="a" * 64,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        assert created.status == "open"
        assert await repository.get("upl_missing") is None
        with pytest.raises(NotFoundError):
            await repository.require("upl_missing")

        first = await repository.record_part(
            upload_id=upload_id,
            part_number=1,
            size_bytes=5,
            sha256="b" * 64,
            storage_key=f"uploads/{upload_id}/parts/00001",
        )
        assert first.part_number == 1
        replacement = await repository.record_part(
            upload_id=upload_id,
            part_number=1,
            size_bytes=5,
            sha256="c" * 64,
            storage_key=f"uploads/{upload_id}/parts/00001",
        )
        assert replacement.sha256 == "c" * 64
        await repository.record_part(
            upload_id=upload_id,
            part_number=2,
            size_bytes=7,
            sha256="d" * 64,
            storage_key=f"uploads/{upload_id}/parts/00002",
        )
        parts = await repository.list_parts(upload_id)
        assert [part.part_number for part in parts] == [1, 2]
        assert await repository.find_part(upload_id, 2) is not None
        assert await repository.find_part(upload_id, 9) is None

        completed = await repository.complete(upload_id)
        assert completed.status == "completed"
        assert completed.completed_at is not None
        with pytest.raises(ConflictError):
            await repository.complete(upload_id)
        with pytest.raises(ConflictError):
            await repository.cancel(upload_id)
        await session.commit()


async def test_upload_repository_cancels_sessions_and_lists_expired_ones(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        repository = UploadRepository(session)
        cancelled_id = new_upload_id()
        await repository.create_session(
            upload_id=cancelled_id,
            filename="observations.csv",
            extension=".csv",
            content_type="text/csv",
            total_bytes=4,
            chunk_size_bytes=4,
            expected_sha256=None,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        await repository.record_part(
            upload_id=cancelled_id,
            part_number=1,
            size_bytes=4,
            sha256="e" * 64,
            storage_key=f"uploads/{cancelled_id}/parts/00001",
        )
        cancelled = await repository.cancel(cancelled_id)
        assert cancelled.status == "cancelled"
        assert await repository.list_parts(cancelled_id) == []

        expired_id = new_upload_id()
        await repository.create_session(
            upload_id=expired_id,
            filename="old.csv",
            extension=".csv",
            content_type="text/csv",
            total_bytes=1,
            chunk_size_bytes=1,
            expected_sha256=None,
            expires_at=datetime.now(UTC) - timedelta(hours=1),
        )
        expired = await repository.list_expired()
        assert [row.id for row in expired] == [expired_id]
        await session.commit()


async def test_run_repository_records_and_finishes_runs(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        _, version_id = await _seed_dataset_version(session)
        repository = RunRepository(session)
        run_id = new_run_id()
        created = await repository.create(
            run_id=run_id,
            dataset_version_id=version_id,
            recipe_hash="f" * 64,
            recipe={"spatial": {"method": "idw"}},
            dataset_sha256="0" * 64,
            boundary_sha256="1" * 64,
            seed=42,
            application_version="0.1.0",
            schema_version="1.0.0",
        )
        assert created.status == "queued"
        assert await repository.get(run_id) is not None
        with pytest.raises(NotFoundError):
            await repository.require("run_missing")
        finished = await repository.finish(run_id, status="succeeded")
        assert finished.status == "succeeded"
        assert finished.finished_at is not None
        assert [row.id for row in await repository.list_for_version(version_id)] == [run_id]
        await session.commit()


async def test_artifact_repository_indexes_artifacts_by_run_and_version(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        _, version_id = await _seed_dataset_version(session)
        repository = ArtifactRepository(session)
        run_id = new_run_id()
        artifact_id = new_artifact_id()
        registered = await repository.register(
            artifact_id=artifact_id,
            kind="datasets",
            sha256="2" * 64,
            size_bytes=1024,
            content_type="application/vnd.apache.parquet",
            storage_key=f"datasets/22/{'2' * 64}/observations.parquet",
            schema_version="1.0.0",
            dataset_version_id=version_id,
            run_id=run_id,
            metadata={"rows": 12},
        )
        assert registered.details == {"rows": 12}
        assert await repository.get(artifact_id) is not None
        with pytest.raises(NotFoundError):
            await repository.require("art_missing")
        assert [row.id for row in await repository.list_for_run(run_id)] == [artifact_id]
        assert [row.id for row in await repository.list_for_version(version_id)] == [artifact_id]
        await session.commit()


async def test_registry_repository_stores_stations_parameters_and_rules(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        _, version_id = await _seed_dataset_version(session)
        repository = RegistryRepository(session)
        station_id = new_station_id()
        await repository.add_station(
            station_id=station_id,
            dataset_version_id=version_id,
            label="Station 1",
            latitude_wgs84=19.7,
            longitude_wgs84=85.2,
            x_projected_m=612345.0,
            y_projected_m=2187654.0,
            source_crs="EPSG:4326",
            analysis_crs="EPSG:32644",
            sector="Outer",
        )
        stations = await repository.list_stations(version_id)
        assert [station.id for station in stations] == [station_id]
        assert stations[0].sector == "Outer"

        parameter_id = new_parameter_id()
        await repository.add_parameter(
            parameter_id=parameter_id,
            dataset_version_id=version_id,
            label="Salinity",
            canonical_unit="psu",
            dimension="[mass_concentration]",
            display_name="Salinity",
            aliases=["sal", "salt"],
            physical_range_min=0.0,
            physical_range_max=45.0,
        )
        parameters = await repository.list_parameters(version_id)
        assert [parameter.id for parameter in parameters] == [parameter_id]
        assert parameters[0].aliases == ["sal", "salt"]

        rule = await repository.upsert_qc_rule(
            rule_id="rule-range-1",
            code="range_outlier",
            severity="warning",
            description="Value outside the registered physical range.",
            version="1.0.0",
            source="registry",
            applicability={"parameters": ["salinity"]},
        )
        assert rule.enabled is True
        updated = await repository.upsert_qc_rule(
            rule_id="rule-range-1",
            code="range_outlier",
            severity="error",
            description="Value outside the registered physical range.",
            version="1.0.0",
            source="registry",
            applicability={"parameters": ["salinity"]},
            enabled=False,
        )
        assert updated.id == rule.id
        assert updated.severity == "error"
        assert updated.enabled is False
        assert await repository.list_qc_rules() == []
        assert [row.code for row in await repository.list_qc_rules(enabled_only=False)] == [
            "range_outlier"
        ]
        await session.commit()


async def test_registry_repository_upserts_methods_and_compatibility(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        repository = RegistryRepository(session)
        method = await repository.upsert_method(
            method_id="method-grab",
            label="Grab sampling",
            description="Surface water grab sample.",
            reference="APHA 4500",
        )
        assert method.label == "Grab sampling"
        updated = await repository.upsert_method(
            method_id="method-grab",
            label="Grab sampling",
            description="Surface water grab sample, in situ.",
            reference="APHA 4500",
        )
        assert updated.id == method.id
        assert updated.description == "Surface water grab sample, in situ."
        assert [row.id for row in await repository.list_methods()] == ["method-grab"]

        record = await repository.record_compatibility(
            api_major=1,
            artifact_schema_version="1.0.0",
            recipe_schema_version="1.0.0",
            application_version="0.1.0",
        )
        assert record.api_major == 1
        refreshed = await repository.record_compatibility(
            api_major=1,
            artifact_schema_version="1.0.0",
            recipe_schema_version="1.0.0",
            application_version="0.2.0",
        )
        assert refreshed.id == record.id
        assert refreshed.application_version == "0.2.0"
        assert len(await repository.list_compatibility()) == 1
        await session.commit()


async def test_repository_sessions_survive_a_reopened_connection(
    prepared_database: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        dataset_id, version_id = await _seed_dataset_version(session)
        await session.commit()

    async with session_factory() as session:
        datasets = DatasetRepository(session)
        version = await datasets.require_version(version_id)
        assert version.dataset_id == dataset_id
        assert version.row_count == 12
