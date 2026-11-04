"""Alembic environment bound to the persistence metadata."""

from __future__ import annotations

from alembic import context
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from trendsmapp.persistence.models import Base

config = context.config
target_metadata = Base.metadata


def _database_url() -> str:
    """Return the database URL used by the migration.

    The environment variable wins so that a migration never runs against a
    different database than the application.
    """
    import os

    url = os.getenv("TRENDSMAPP_DATABASE_URL", "").strip()
    if not url:
        url = config.get_main_option("sqlalchemy.url", "")
    if not url:
        raise RuntimeError("TRENDSMAPP_DATABASE_URL must be set to run migrations.")
    return url


def run_migrations_offline() -> None:
    """Run migrations without a live database connection."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations against a live connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations against an async engine."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _database_url()
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    import asyncio

    asyncio.run(run_migrations_online())
