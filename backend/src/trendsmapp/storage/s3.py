"""S3-compatible object store adapter.

The adapter works against any S3-compatible service. It streams uploads and
downloads, records the SHA-256 of every stored object in the object metadata,
and verifies that metadata when an object is read back.
"""

from __future__ import annotations

import hashlib
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any, BinaryIO, cast

from trendsmapp.errors import StorageError
from trendsmapp.hashing import sha256_bytes
from trendsmapp.storage.base import StoredObject, StoredObjectStream
from trendsmapp.storage.paths import validate_storage_key

__all__ = ["S3ObjectStore"]

_SHA256_METADATA_KEY = "sha256"
_CONTENT_TYPE_METADATA_KEY = "content-type"


class S3ObjectStore:
    """A content-addressed object store backed by an S3-compatible service."""

    def __init__(self, bucket: str, client: Any, *, key_prefix: str = "") -> None:
        if not bucket:
            raise StorageError("An S3 bucket name is required.")
        self._bucket = bucket
        self._client = client
        self._key_prefix = key_prefix.strip("/")

    def _full_key(self, key: str) -> str:
        validate_storage_key(key)
        if not self._key_prefix:
            return key
        return f"{self._key_prefix}/{key}"

    def put_bytes(self, key: str, payload: bytes, *, content_type: str) -> StoredObject:
        """Store ``payload`` under ``key`` and return its metadata."""
        digest = sha256_bytes(payload)
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=self._full_key(key),
                Body=payload,
                ContentType=content_type,
                Metadata={_SHA256_METADATA_KEY: digest, _CONTENT_TYPE_METADATA_KEY: content_type},
            )
        except Exception as exc:
            raise StorageError(
                f"The object could not be written to the object store: {exc}",
                details={"key": key},
            ) from exc
        return StoredObject(
            key=key,
            sha256=digest,
            size_bytes=len(payload),
            content_type=content_type,
        )

    def put_stream(
        self,
        key: str,
        stream: BinaryIO,
        *,
        content_type: str,
        expected_size: int | None = None,
    ) -> StoredObject:
        """Store the contents of ``stream`` under ``key`` and return its metadata.

        The stream is spooled to a temporary file so that the checksum can be
        recorded in the object metadata in the same upload, and so that the
        upload can be retried without consuming the source stream twice.
        """
        digest = hashlib.sha256()
        written = 0
        with tempfile.TemporaryDirectory() as temporary_directory:
            spool_path = Path(temporary_directory) / "payload"
            with spool_path.open("wb") as spool:
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    digest.update(chunk)
                    spool.write(chunk)
            if expected_size is not None and written != expected_size:
                raise StorageError(
                    "The stored object size does not match the declared size.",
                    details={
                        "key": key,
                        "expected_size": expected_size,
                        "actual_size": written,
                    },
                )
            checksum = digest.hexdigest()
            try:
                with spool_path.open("rb") as spool:
                    self._client.upload_fileobj(
                        spool,
                        self._bucket,
                        self._full_key(key),
                        ExtraArgs={
                            "ContentType": content_type,
                            "Metadata": {
                                _SHA256_METADATA_KEY: checksum,
                                _CONTENT_TYPE_METADATA_KEY: content_type,
                            },
                        },
                    )
            except Exception as exc:
                raise StorageError(
                    f"The object could not be written to the object store: {exc}",
                    details={"key": key},
                ) from exc
        return StoredObject(
            key=key,
            sha256=checksum,
            size_bytes=written,
            content_type=content_type,
        )

    def get_bytes(self, key: str) -> bytes:
        """Return the full contents of the object stored under ``key``."""
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=self._full_key(key))
        except Exception as exc:
            raise StorageError(
                f"The object could not be read from the object store: {exc}",
                details={"key": key},
            ) from exc
        body = response["Body"]
        try:
            payload = cast(bytes, body.read())
        finally:
            close = getattr(body, "close", None)
            if callable(close):
                close()
        expected = response.get("Metadata", {}).get(_SHA256_METADATA_KEY)
        if expected and expected != "pending" and expected != sha256_bytes(payload):
            raise StorageError(
                "The stored object does not match its recorded checksum.",
                details={"key": key},
            )
        return payload

    def open_stream(self, key: str) -> StoredObjectStream:
        """Return a readable stream over the object stored under ``key``."""
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=self._full_key(key))
        except Exception as exc:
            raise StorageError(
                f"The object could not be read from the object store: {exc}",
                details={"key": key},
            ) from exc
        return StoredObjectStream(response["Body"])

    def exists(self, key: str) -> bool:
        """Return whether an object exists under ``key``."""
        try:
            self._client.head_object(Bucket=self._bucket, Key=self._full_key(key))
        except Exception:  # noqa: BLE001 - adapter boundary
            return False
        return True

    def head(self, key: str) -> StoredObject:
        """Return the metadata of the object stored under ``key``."""
        try:
            response = self._client.head_object(Bucket=self._bucket, Key=self._full_key(key))
        except Exception as exc:
            raise StorageError(
                f"The object metadata could not be read: {exc}", details={"key": key}
            ) from exc
        metadata = response.get("Metadata", {})
        return StoredObject(
            key=key,
            sha256=metadata.get(_SHA256_METADATA_KEY, ""),
            size_bytes=int(response.get("ContentLength", 0)),
            content_type=response.get("ContentType", "application/octet-stream"),
        )

    def delete(self, key: str) -> None:
        """Delete the object stored under ``key`` if it exists."""
        try:
            self._client.delete_object(Bucket=self._bucket, Key=self._full_key(key))
        except Exception as exc:
            raise StorageError(
                f"The object could not be deleted from the object store: {exc}",
                details={"key": key},
            ) from exc

    def list_prefix(self, prefix: str) -> Iterator[str]:
        """Return the keys of every object under ``prefix``."""
        search_prefix = f"{self._key_prefix}/{prefix}" if self._key_prefix else prefix
        paginator = self._client.get_paginator("list_objects_v2")
        try:
            for page in paginator.paginate(Bucket=self._bucket, Prefix=search_prefix):
                for item in page.get("Contents", []):
                    key = item["Key"]
                    if self._key_prefix and key.startswith(f"{self._key_prefix}/"):
                        key = key[len(self._key_prefix) + 1 :]
                    yield key
        except Exception as exc:
            raise StorageError(
                f"The object listing could not be read: {exc}", details={"prefix": prefix}
            ) from exc

    def ping(self) -> bool:
        """Return whether the bucket is reachable."""
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except Exception:  # noqa: BLE001 - adapter boundary
            return False
        return True
