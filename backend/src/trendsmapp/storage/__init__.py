"""Storage adapters for immutable, content-addressed artifacts."""

from trendsmapp.storage.base import ObjectStore, StoredObject, StoredObjectStream
from trendsmapp.storage.factory import create_object_store
from trendsmapp.storage.local import LocalObjectStore
from trendsmapp.storage.paths import (
    build_artifact_key,
    build_raw_upload_key,
    build_upload_part_key,
    safe_filename,
    validate_storage_key,
)
from trendsmapp.storage.s3 import S3ObjectStore

__all__ = [
    "LocalObjectStore",
    "ObjectStore",
    "S3ObjectStore",
    "StoredObject",
    "StoredObjectStream",
    "build_artifact_key",
    "build_raw_upload_key",
    "build_upload_part_key",
    "create_object_store",
    "safe_filename",
    "validate_storage_key",
]
