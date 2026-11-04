"""Supported contract and method metadata."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from trendsmapp.api.dependencies import SettingsDependency
from trendsmapp.contracts.versions import (
    API_MAJOR_VERSION,
    APPLICATION_VERSION,
    ARTIFACT_SCHEMA_VERSION,
    RECIPE_SCHEMA_VERSION,
    SUPPORTED_API_MAJOR_VERSIONS,
    SUPPORTED_ARTIFACT_SCHEMA_VERSIONS,
    SUPPORTED_RECIPE_SCHEMA_VERSIONS,
)
from trendsmapp.services.capabilities import build_capabilities

__all__ = ["router"]

router = APIRouter(prefix="/api/v1", tags=["capabilities"])


@router.get("/capabilities")
async def capabilities(request: Request, settings: SettingsDependency) -> dict[str, Any]:
    """Return the formats, methods, versions, and limits of this deployment."""
    engine = request.app.state.engine
    dialect = engine.dialect.name
    return build_capabilities(settings, database_dialect=dialect)


@router.get("/contracts/versions")
async def contract_versions() -> dict[str, Any]:
    """Return the contract versions this deployment speaks."""
    return {
        "api_major": API_MAJOR_VERSION,
        "application_version": APPLICATION_VERSION,
        "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        "recipe_schema_version": RECIPE_SCHEMA_VERSION,
        "supported_api_majors": list(SUPPORTED_API_MAJOR_VERSIONS),
        "supported_artifact_schema_versions": list(SUPPORTED_ARTIFACT_SCHEMA_VERSIONS),
        "supported_recipe_schema_versions": list(SUPPORTED_RECIPE_SCHEMA_VERSIONS),
    }
