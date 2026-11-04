"""Shared fixtures for the backend test suite."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from trendsmapp.api.app import create_app
from trendsmapp.persistence.database import create_engine_for_settings, create_session_factory
from trendsmapp.settings import Settings
from trendsmapp.storage.local import LocalObjectStore

TEST_DATABASE_URL_TEMPLATE = "sqlite+aiosqlite:///{path}"
TESTDATA_DIRECTORY = Path(__file__).resolve().parents[1] / "testdata"


@pytest.fixture
def testdata_path() -> Callable[[str], Path]:
    """Return the path of a fixture file inside ``backend/testdata``."""

    def resolve(name: str) -> Path:
        return TESTDATA_DIRECTORY / name

    return resolve


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Return settings that use a temporary database and object store."""
    return Settings(
        environment="test",
        database_url=TEST_DATABASE_URL_TEMPLATE.format(path=(tmp_path / "test.db").as_posix()),
        object_store_backend="local",
        local_storage_root=tmp_path / "objects",
        log_level="warning",
        log_json=False,
        worker_poll_interval_seconds=0.01,
        worker_heartbeat_interval_seconds=0.05,
        worker_stale_after_seconds=30,
    )


@pytest.fixture
def store(settings: Settings) -> LocalObjectStore:
    """Return a local object store rooted in a temporary directory."""
    return LocalObjectStore(settings.local_storage_root)


@pytest_asyncio.fixture
async def engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    """Return an async engine bound to the temporary database."""
    created = create_engine_for_settings(settings)
    yield created
    await created.dispose()


@pytest_asyncio.fixture
async def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Return a session factory bound to the test engine."""
    return create_session_factory(engine)


@pytest_asyncio.fixture
async def prepared_database(engine: AsyncEngine) -> AsyncEngine:
    """Return an engine whose schema has been created from the ORM metadata."""
    from trendsmapp.persistence.models import Base

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine


@pytest_asyncio.fixture
async def client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    """Return an HTTP client bound to the application with its lifespan running."""
    application = create_app(settings=settings)
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as http_client:
            yield http_client
