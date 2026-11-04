"""Object-store factory.

The adapter is selected once at process startup from validated settings. A
misconfigured deployment fails immediately instead of failing on the first
upload.
"""

from __future__ import annotations

from typing import Any

from trendsmapp.errors import ConfigurationError
from trendsmapp.settings import Settings, get_settings
from trendsmapp.storage.base import ObjectStore
from trendsmapp.storage.local import LocalObjectStore
from trendsmapp.storage.s3 import S3ObjectStore

__all__ = ["create_object_store", "create_s3_client"]


def create_s3_client(settings: Settings) -> Any:
    """Build the boto3 client for the configured S3-compatible service."""
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise ConfigurationError("boto3 is required for the S3 object store.") from exc
    access_key = settings.s3_access_key_id.get_secret_value() if settings.s3_access_key_id else None
    secret_key = (
        settings.s3_secret_access_key.get_secret_value() if settings.s3_secret_access_key else None
    )
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        region_name=settings.s3_region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )


def create_object_store(settings: Settings | None = None) -> ObjectStore:
    """Return the object store selected by the configuration."""
    resolved = settings or get_settings()
    if resolved.object_store_backend == "local":
        return LocalObjectStore(resolved.local_storage_root)
    if resolved.object_store_backend == "s3":
        if not resolved.s3_bucket:
            raise ConfigurationError("TRENDSMAPP_S3_BUCKET is required for the S3 object store.")
        return S3ObjectStore(resolved.s3_bucket, create_s3_client(resolved))
    raise ConfigurationError(
        f"Unsupported object store backend: {resolved.object_store_backend}",
        details={"backend": resolved.object_store_backend},
    )
