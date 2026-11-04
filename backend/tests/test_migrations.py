"""Integration test for the initial Alembic migration."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

BACKEND_ROOT = Path(__file__).resolve().parents[1]

EXPECTED_TABLES = {
    "artifacts",
    "contract_compatibility",
    "dataset_versions",
    "datasets",
    "jobs",
    "methods",
    "parameters",
    "provenance_events",
    "qc_rules",
    "runs",
    "stations",
    "upload_parts",
    "uploads",
}


def _alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    config.set_main_option("prepend_sys_path", str(BACKEND_ROOT / "src"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.mark.parametrize("direction", ["upgrade", "downgrade"])
async def test_initial_migration_applies_and_reverts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, direction: str
) -> None:
    database_path = (tmp_path / "migration.db").as_posix()
    database_url = f"sqlite+aiosqlite:///{database_path}"
    monkeypatch.setenv("TRENDSMAPP_DATABASE_URL", database_url)
    config = _alembic_config(database_url)

    await asyncio.to_thread(command.upgrade, config, "head")

    engine = create_async_engine(database_url)
    async with engine.connect() as connection:
        tables = await connection.run_sync(
            lambda sync_connection: set(inspect(sync_connection).get_table_names())
        )
    await engine.dispose()
    assert tables >= EXPECTED_TABLES

    await asyncio.to_thread(command.downgrade, config, "base")

    engine = create_async_engine(database_url)
    async with engine.connect() as connection:
        remaining = await connection.run_sync(
            lambda sync_connection: set(inspect(sync_connection).get_table_names())
        )
    await engine.dispose()
    assert not (EXPECTED_TABLES & remaining)
