"""Capability reporting.

The report separates what this deployment is *configured* to allow from what
this build actually *implements*. A format, spatial method, temporal method, or
model family appears in the implemented lists only when the corresponding code
path exists and is exercised by tests; otherwise the capability is absent
rather than promised and failing later.
"""

from __future__ import annotations

from typing import Any

from trendsmapp.constants import (
    API_MAJOR_VERSION,
    CHUNK_SIZE_BOUNDS_BYTES,
    DEFAULT_UPLOAD_CHUNK_BYTES,
    GRID_CELL_LIMITS,
    MAX_ANIMATION_FRAMES,
    MAX_CANDIDATE_MODELS,
    MAX_FILE_SIZE_BYTES,
    MAX_INGESTED_COLUMNS,
    MAX_INGESTED_ROWS,
    MAX_SEARCH_TRIALS_PER_MODEL,
    MAX_SHAP_ROWS,
    MAX_UNIQUE_TIMESTAMPS_PER_RUN,
    MAX_WORKBOOK_CELLS,
    MAX_WORKBOOK_SHEETS,
    PREVIEW_ROW_LIMIT,
)
from trendsmapp.contracts.versions import (
    ARTIFACT_SCHEMA_VERSION,
    RECIPE_SCHEMA_VERSION,
    SUPPORTED_API_MAJOR_VERSIONS,
    SUPPORTED_ARTIFACT_SCHEMA_VERSIONS,
    SUPPORTED_RECIPE_SCHEMA_VERSIONS,
)
from trendsmapp.settings import Settings
from trendsmapp.version import APPLICATION_VERSION

__all__ = [
    "IMPLEMENTED_FILE_FORMATS",
    "IMPLEMENTED_MODEL_FAMILIES",
    "IMPLEMENTED_SPATIAL_METHODS",
    "IMPLEMENTED_TEMPORAL_METHODS",
    "build_capabilities",
]

#: File formats this build can ingest. Populated when the readers exist.
IMPLEMENTED_FILE_FORMATS: tuple[str, ...] = ()

#: Spatial interpolation methods this build can execute.
IMPLEMENTED_SPATIAL_METHODS: tuple[str, ...] = ()

#: Temporal interpolation methods this build can execute.
IMPLEMENTED_TEMPORAL_METHODS: tuple[str, ...] = ()

#: Regression model families this build can train.
IMPLEMENTED_MODEL_FAMILIES: tuple[str, ...] = ()


def build_capabilities(settings: Settings, *, database_dialect: str) -> dict[str, Any]:
    """Return the capability document for the running deployment."""
    return {
        "application_version": APPLICATION_VERSION,
        "api_major": API_MAJOR_VERSION,
        "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        "recipe_schema_version": RECIPE_SCHEMA_VERSION,
        "supported_api_majors": list(SUPPORTED_API_MAJOR_VERSIONS),
        "supported_artifact_schema_versions": list(SUPPORTED_ARTIFACT_SCHEMA_VERSIONS),
        "supported_recipe_schema_versions": list(SUPPORTED_RECIPE_SCHEMA_VERSIONS),
        "file_formats": list(IMPLEMENTED_FILE_FORMATS),
        "spatial_methods": list(IMPLEMENTED_SPATIAL_METHODS),
        "temporal_methods": list(IMPLEMENTED_TEMPORAL_METHODS),
        "model_families": list(IMPLEMENTED_MODEL_FAMILIES),
        "limits": {
            "upload_max_bytes": settings.upload_max_bytes,
            "upload_chunk_bytes": settings.upload_chunk_bytes,
            "upload_chunk_size_bounds": list(CHUNK_SIZE_BOUNDS_BYTES),
            "upload_session_ttl_seconds": settings.upload_session_ttl_seconds,
            "preview_row_limit": settings.preview_row_limit,
            "ingestion_max_rows": MAX_INGESTED_ROWS,
            "ingestion_max_columns": MAX_INGESTED_COLUMNS,
            "max_grid_cells": settings.max_grid_cells,
            "max_timestamps_per_run": settings.max_timestamps_per_run,
            "max_animation_frames": settings.max_animation_frames,
            "max_workbook_sheets": settings.max_workbook_sheets,
            "max_workbook_cells": settings.max_workbook_cells,
            "max_candidate_models": settings.max_candidate_models,
            "max_search_trials_per_model": settings.max_search_trials_per_model,
            "max_shap_rows": settings.max_shap_rows,
        },
        "hard_ceilings": {
            "upload_max_bytes": MAX_FILE_SIZE_BYTES,
            "upload_chunk_bytes": DEFAULT_UPLOAD_CHUNK_BYTES,
            "preview_row_limit": PREVIEW_ROW_LIMIT,
            "ingestion_max_rows": MAX_INGESTED_ROWS,
            "ingestion_max_columns": MAX_INGESTED_COLUMNS,
            "grid_cell_limits": list(GRID_CELL_LIMITS),
            "max_timestamps_per_run": MAX_UNIQUE_TIMESTAMPS_PER_RUN,
            "max_animation_frames": MAX_ANIMATION_FRAMES,
            "max_workbook_sheets": MAX_WORKBOOK_SHEETS,
            "max_workbook_cells": MAX_WORKBOOK_CELLS,
            "max_candidate_models": MAX_CANDIDATE_MODELS,
            "max_search_trials_per_model": MAX_SEARCH_TRIALS_PER_MODEL,
            "max_shap_rows": MAX_SHAP_ROWS,
        },
        "configuration": {
            "analysis_crs": settings.analysis_crs,
            "object_store_backend": settings.object_store_backend,
            "database_dialect": database_dialect,
            "environment": settings.environment,
            "ingestion_accept_cached_formula_values": (
                settings.ingestion_accept_cached_formula_values
            ),
        },
    }
