"""Process configuration, validated once at startup.

Settings are read from the environment with the ``TRENDSMAPP_`` prefix. The
model validates cross-field invariants that cannot be expressed per field: for
example, production requires an S3-compatible object store, PostgreSQL, and
explicit CORS origins, and refuses to start with an insecure configuration.

The settings object is created lazily through :func:`get_settings` so that
importing this module never reads the environment. Process startup code and the
FastAPI dependency provider call :func:`get_settings` explicitly.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from trendsmapp.constants import (
    CHUNK_SIZE_BOUNDS_BYTES,
    DEFAULT_ANALYSIS_CRS,
    DEFAULT_UPLOAD_CHUNK_BYTES,
    GRID_CELL_LIMITS,
    MAX_ANIMATION_FRAMES,
    MAX_CANDIDATE_MODELS,
    MAX_FILE_SIZE_BYTES,
    MAX_SEARCH_TRIALS_PER_MODEL,
    MAX_SHAP_ROWS,
    MAX_UNIQUE_TIMESTAMPS_PER_RUN,
    MAX_WORKBOOK_CELLS,
    MAX_WORKBOOK_SHEETS,
    PREVIEW_ROW_LIMIT,
)

__all__ = ["Environment", "Settings", "get_settings"]

Environment = Literal["development", "test", "staging", "production"]


def _split_csv(value: object) -> object:
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        if stripped.startswith("["):
            return value
        return [item.strip() for item in stripped.split(",") if item.strip()]
    return value


class Settings(BaseSettings):
    """Validated configuration for every Trendsmapp process."""

    model_config = SettingsConfigDict(
        env_prefix="TRENDSMAPP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    application_name: str = "trendsmapp"
    environment: Environment = "development"
    debug: bool = False

    api_major_version: int = Field(default=1, ge=1)

    database_url: str = "sqlite+aiosqlite:///./trendsmapp-dev.db"
    database_echo: bool = False
    database_pool_size: int = Field(default=5, ge=1, le=50)
    database_max_overflow: int = Field(default=5, ge=0, le=50)

    object_store_backend: Literal["local", "s3"] = "local"
    local_storage_root: Path = Path("var/objects")
    s3_endpoint_url: str | None = None
    s3_bucket: str | None = None
    s3_region: str | None = None
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None

    upload_max_bytes: int = Field(default=MAX_FILE_SIZE_BYTES, gt=0, le=MAX_FILE_SIZE_BYTES)
    upload_chunk_bytes: int = Field(
        default=DEFAULT_UPLOAD_CHUNK_BYTES,
        ge=CHUNK_SIZE_BOUNDS_BYTES[0],
        le=CHUNK_SIZE_BOUNDS_BYTES[1],
    )
    upload_session_ttl_seconds: int = Field(default=86_400, ge=300, le=604_800)
    upload_max_concurrent_sessions: int = Field(default=3, ge=1, le=20)

    ingestion_accept_cached_formula_values: bool = False

    preview_row_limit: int = Field(default=PREVIEW_ROW_LIMIT, ge=1, le=5_000)
    max_grid_cells: int = Field(
        default=GRID_CELL_LIMITS[1], ge=GRID_CELL_LIMITS[0], le=GRID_CELL_LIMITS[1]
    )
    max_timestamps_per_run: int = Field(
        default=MAX_UNIQUE_TIMESTAMPS_PER_RUN, ge=1, le=MAX_UNIQUE_TIMESTAMPS_PER_RUN
    )
    max_animation_frames: int = Field(default=MAX_ANIMATION_FRAMES, ge=1, le=MAX_ANIMATION_FRAMES)
    max_workbook_sheets: int = Field(default=MAX_WORKBOOK_SHEETS, ge=1, le=MAX_WORKBOOK_SHEETS)
    max_workbook_cells: int = Field(default=MAX_WORKBOOK_CELLS, ge=1, le=MAX_WORKBOOK_CELLS)
    max_candidate_models: int = Field(default=MAX_CANDIDATE_MODELS, ge=1, le=MAX_CANDIDATE_MODELS)
    max_search_trials_per_model: int = Field(
        default=MAX_SEARCH_TRIALS_PER_MODEL, ge=1, le=MAX_SEARCH_TRIALS_PER_MODEL
    )
    max_shap_rows: int = Field(default=MAX_SHAP_ROWS, ge=1, le=MAX_SHAP_ROWS)

    analysis_crs: str = DEFAULT_ANALYSIS_CRS
    default_boundary_resource: str = "resources/default_boundary.geojson"

    cors_allow_origins: list[str] = Field(default_factory=list)
    trusted_hosts: list[str] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1", "testserver"]
    )
    request_max_body_bytes: int = Field(default=16 * 1024 * 1024, gt=0, le=MAX_FILE_SIZE_BYTES)

    worker_poll_interval_seconds: float = Field(default=1.0, gt=0, le=60)
    worker_heartbeat_interval_seconds: float = Field(default=10.0, gt=0, le=300)
    worker_stale_after_seconds: int = Field(default=300, ge=30, le=86_400)
    worker_concurrency: int = Field(default=1, ge=1, le=16)

    log_level: Literal["debug", "info", "warning", "error", "critical"] = "info"
    log_json: bool = True

    @field_validator("cors_allow_origins", "trusted_hosts", mode="before")
    @classmethod
    def _split_comma_separated(cls, value: object) -> object:
        return _split_csv(value)

    @model_validator(mode="after")
    def _validate_environment(self) -> Settings:
        if self.environment == "production":
            problems: list[str] = []
            if self.object_store_backend != "s3":
                problems.append("TRENDSMAPP_OBJECT_STORE_BACKEND must be 's3' in production")
            if not self.s3_bucket:
                problems.append("TRENDSMAPP_S3_BUCKET is required in production")
            if not self.database_url.startswith(("postgresql", "postgres")):
                problems.append("TRENDSMAPP_DATABASE_URL must be a PostgreSQL URL in production")
            if not self.cors_allow_origins:
                problems.append(
                    "TRENDSMAPP_CORS_ALLOW_ORIGINS must list the public frontend origin"
                )
            if not self.trusted_hosts:
                problems.append("TRENDSMAPP_TRUSTED_HOSTS must list the public hostnames")
            if problems:
                raise ValueError("; ".join(problems))
        if self.object_store_backend == "s3" and not self.s3_bucket:
            raise ValueError(
                "TRENDSMAPP_S3_BUCKET is required when the S3 object store is selected"
            )
        if self.request_max_body_bytes > self.upload_max_bytes:
            raise ValueError("TRENDSMAPP_REQUEST_MAX_BODY_BYTES cannot exceed the upload ceiling")
        return self

    @property
    def is_production(self) -> bool:
        """Return whether the process runs with production guarantees enabled."""
        return self.environment == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings instance, constructing it on first use."""
    return Settings()
