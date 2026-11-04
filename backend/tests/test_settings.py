"""Tests for configuration validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from trendsmapp.settings import Settings


def test_development_defaults_are_usable() -> None:
    configured = Settings()
    assert configured.object_store_backend == "local"
    assert configured.environment == "development"
    assert configured.upload_chunk_bytes == 5 * 1024 * 1024


def test_production_requires_s3_postgres_and_explicit_origins() -> None:
    with pytest.raises(PydanticValidationError) as failure:
        Settings(environment="production")
    message = str(failure.value)
    assert "OBJECT_STORE_BACKEND" in message
    assert "S3_BUCKET" in message
    assert "DATABASE_URL" in message
    assert "CORS_ALLOW_ORIGINS" in message


def test_production_accepts_a_complete_configuration() -> None:
    configured = Settings(
        environment="production",
        object_store_backend="s3",
        s3_bucket="trendsmapp",
        database_url="postgresql+asyncpg://user:pass@db/trendsmapp",
        cors_allow_origins=["https://trendsmapp.example"],
        trusted_hosts=["trendsmapp.example"],
    )
    assert configured.is_production


def test_s3_backend_requires_a_bucket() -> None:
    with pytest.raises(PydanticValidationError):
        Settings(object_store_backend="s3")


def test_request_body_limit_cannot_exceed_the_upload_ceiling() -> None:
    with pytest.raises(PydanticValidationError):
        Settings(upload_max_bytes=1000, request_max_body_bytes=2000)


def test_chunk_size_must_stay_inside_the_negotiated_bounds() -> None:
    with pytest.raises(PydanticValidationError):
        Settings(upload_chunk_bytes=1024)
    with pytest.raises(PydanticValidationError):
        Settings(upload_chunk_bytes=64 * 1024 * 1024)


def test_comma_separated_lists_are_parsed() -> None:
    configured = Settings(cors_allow_origins="https://a.example, https://b.example")
    assert configured.cors_allow_origins == ["https://a.example", "https://b.example"]
