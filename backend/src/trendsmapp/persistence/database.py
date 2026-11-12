"""Async engine, session factory, health check, and shutdown.

The engine is created once per process from validated settings. Production
uses PostgreSQL through asyncpg; development and tests use SQLite through
aiosqlite. The dialect is detected from the URL so that the same code path
serves both, including the row-locking behaviour used by the worker.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from trendsmapp.errors import ConfigurationError
from trendsmapp.logging_config import get_logger
from trendsmapp.settings import Settings, get_settings

logger = get_logger(__name__)

__all__ = [
    "create_engine_for_settings",
    "create_session_factory",
    "database_health",
    "dispose_engine",
    "session_scope",
]


def _engine_kwargs(settings: Settings) -> dict[str, Any]:
    """Engine-level kwargs; pool sizing applies only to the pooled PostgreSQL path.

    These must NOT go into ``connect_args`` — that dict is passed to the DBAPI's
    ``connect()`` (e.g. asyncpg), which rejects pool keywords with a TypeError.
    SQLite keeps its default pool behavior.
    """
    if settings.database_url.startswith("sqlite"):
        return {}
    return {
        "pool_size": settings.database_pool_size,
        "max_overflow": settings.database_max_overflow,
        "pool_recycle": 300,
        "pool_pre_ping": True,
    }


def create_engine_for_settings(settings: Settings | None = None) -> AsyncEngine:
    """Create the async engine for the configured database."""
    resolved = settings or get_settings()
    url = resolved.database_url
    if not url.startswith(("postgresql", "postgres", "sqlite")):
        raise ConfigurationError(
            "TRENDSMAPP_DATABASE_URL must use the postgresql+asyncpg or sqlite+aiosqlite scheme.",
            details={"database_url": url.split("://", 1)[0]},
        )
    return create_async_engine(
        url,
        echo=resolved.database_echo,
        future=True,
        **_engine_kwargs(resolved),
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create the session factory bound to ``engine``."""
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


@asynccontextmanager
async def session_scope(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Run a unit of work inside a transaction, rolling back on failure."""
    session = session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def database_health(engine: AsyncEngine) -> bool:
    """Return whether the database answers a trivial query."""
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - health probes must not raise
        logger.warning(
            "database health probe failed",
            error=repr(exc),
            url=engine.url.render_as_string(hide_password=True),
        )
        return False
    return True


async def dispose_engine(engine: AsyncEngine) -> None:
    """Release every pooled connection held by the engine."""
    await engine.dispose()
