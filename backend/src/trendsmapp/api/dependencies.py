"""Dependency providers for settings, sessions, repositories, and storage.

Route handlers obtain everything they need through these providers, which
keeps the HTTP layer free of construction logic and makes the same services
reachable from the worker.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from trendsmapp.persistence.database import session_scope
from trendsmapp.persistence.repositories import (
    ArtifactRepository,
    DatasetRepository,
    JobRepository,
    RegistryRepository,
    RunRepository,
    UploadRepository,
)
from trendsmapp.settings import Settings, get_settings
from trendsmapp.storage.base import ObjectStore

__all__ = [
    "SettingsDependency",
    "get_artifact_repository",
    "get_dataset_repository",
    "get_job_repository",
    "get_object_store",
    "get_registry_repository",
    "get_run_repository",
    "get_session",
    "get_settings_dependency",
    "get_upload_repository",
]


def get_settings_dependency(request: Request) -> Settings:
    """Return the settings of the running application."""
    configured = getattr(request.app.state, "settings", None)
    if isinstance(configured, Settings):
        return configured
    return get_settings()


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield a transactional database session."""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with session_scope(factory) as session:
        yield session


def get_object_store(request: Request) -> ObjectStore:
    """Return the configured object store."""
    store: ObjectStore = request.app.state.object_store
    return store


def get_job_repository(session: Annotated[AsyncSession, Depends(get_session)]) -> JobRepository:
    """Return a job repository bound to the request session."""
    return JobRepository(session)


def get_dataset_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DatasetRepository:
    """Return a dataset repository bound to the request session."""
    return DatasetRepository(session)


def get_upload_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UploadRepository:
    """Return an upload repository bound to the request session."""
    return UploadRepository(session)


def get_run_repository(session: Annotated[AsyncSession, Depends(get_session)]) -> RunRepository:
    """Return a run repository bound to the request session."""
    return RunRepository(session)


def get_artifact_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ArtifactRepository:
    """Return an artifact repository bound to the request session."""
    return ArtifactRepository(session)


def get_registry_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RegistryRepository:
    """Return a registry repository bound to the request session."""
    return RegistryRepository(session)


SettingsDependency = Annotated[Settings, Depends(get_settings_dependency)]


def get_engine(request: Request) -> AsyncEngine:
    """Return the database engine of the running application."""
    engine: AsyncEngine = request.app.state.engine
    return engine
