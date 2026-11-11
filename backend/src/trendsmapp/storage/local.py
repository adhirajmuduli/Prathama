"""Atomic local filesystem object store.

The local adapter is used for development and tests. Writes go to a temporary
file in the same directory and are moved into place with :func:`os.replace`,
so a reader never observes a partially written object. Every write computes
the SHA-256 of the exact bytes that were stored.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO

from trendsmapp.errors import StorageError
from trendsmapp.hashing import sha256_stream
from trendsmapp.storage.base import StoredObject, StoredObjectStream
from trendsmapp.storage.paths import validate_storage_key

__all__ = ["LocalObjectStore"]

_PARTIAL_SUFFIX = ".partial"


class LocalObjectStore:
    """A content-addressed object store backed by a local directory."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        """Return the directory that holds the stored objects."""
        return self._root

    def _path_for(self, key: str) -> Path:
        validate_storage_key(key)
        candidate = (self._root / key).resolve()
        if candidate != self._root and self._root not in candidate.parents:
            raise StorageError(
                "The storage key resolves outside the object store root.",
                details={"key": key},
            )
        return candidate

    def put_bytes(self, key: str, payload: bytes, *, content_type: str) -> StoredObject:
        """Store ``payload`` under ``key`` and return its metadata."""
        destination = self._path_for(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary_name = tempfile.mkstemp(dir=destination.parent, suffix=".partial")
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(handle, "wb") as output:
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary_path, destination)
        except OSError as exc:
            temporary_path.unlink(missing_ok=True)
            raise StorageError(
                f"The object could not be written to the store: {exc}",
                details={"key": key},
            ) from exc
        return StoredObject(
            key=key,
            sha256=_sha256_of_file(destination),
            size_bytes=destination.stat().st_size,
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
        """Store the contents of ``stream`` under ``key`` and return its metadata."""
        destination = self._path_for(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary_name = tempfile.mkstemp(dir=destination.parent, suffix=".partial")
        temporary_path = Path(temporary_name)
        digest_holder: list[str] = []
        written = 0
        try:
            with os.fdopen(handle, "wb") as output, tempfile.TemporaryFile() as digest_file:
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    output.write(chunk)
                    digest_file.write(chunk)
                output.flush()
                os.fsync(output.fileno())
                digest_file.seek(0)
                digest_holder.append(sha256_stream(digest_file))
            if expected_size is not None and written != expected_size:
                raise StorageError(
                    "The stored object size does not match the declared size.",
                    details={"key": key, "expected_size": expected_size, "actual_size": written},
                )
            os.replace(temporary_path, destination)
        except OSError as exc:
            temporary_path.unlink(missing_ok=True)
            raise StorageError(
                f"The object could not be written to the store: {exc}",
                details={"key": key},
            ) from exc
        except StorageError:
            temporary_path.unlink(missing_ok=True)
            raise
        return StoredObject(
            key=key,
            sha256=digest_holder[0],
            size_bytes=written,
            content_type=content_type,
        )

    def get_bytes(self, key: str) -> bytes:
        """Return the full contents of the object stored under ``key``."""
        path = self._path_for(key)
        try:
            return path.read_bytes()
        except FileNotFoundError as exc:
            raise StorageError(
                "The requested object does not exist.", details={"key": key}
            ) from exc
        except OSError as exc:
            raise StorageError(
                f"The object could not be read from the store: {exc}", details={"key": key}
            ) from exc

    def open_stream(self, key: str) -> StoredObjectStream:
        """Return a readable stream over the object stored under ``key``."""
        path = self._path_for(key)
        try:
            return StoredObjectStream(path.open("rb"))
        except FileNotFoundError as exc:
            raise StorageError(
                "The requested object does not exist.", details={"key": key}
            ) from exc
        except OSError as exc:
            raise StorageError(
                f"The object could not be read from the store: {exc}", details={"key": key}
            ) from exc

    def exists(self, key: str) -> bool:
        """Return whether an object exists under ``key``."""
        return self._path_for(key).is_file()

    def head(self, key: str) -> StoredObject:
        """Return the metadata of the object stored under ``key``."""
        path = self._path_for(key)
        if not path.is_file():
            raise StorageError("The requested object does not exist.", details={"key": key})
        return StoredObject(
            key=key,
            sha256=_sha256_of_file(path),
            size_bytes=path.stat().st_size,
            content_type="application/octet-stream",
        )

    def delete(self, key: str) -> None:
        """Delete the object stored under ``key`` if it exists."""
        path = self._path_for(key)
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise StorageError(
                f"The object could not be deleted from the store: {exc}", details={"key": key}
            ) from exc

    def list_prefix(self, prefix: str) -> Iterator[str]:
        """Return the keys of every object under ``prefix``."""
        base = self._root
        if prefix:
            base = (self._root / prefix).resolve()
            if base != self._root and self._root not in base.parents:
                raise StorageError(
                    "The storage prefix resolves outside the object store root.",
                    details={"prefix": prefix},
                )
        if not base.exists():
            return
        for path in sorted(base.rglob("*")):
            if path.is_file() and not path.name.endswith(_PARTIAL_SUFFIX):
                yield path.relative_to(self._root).as_posix()

    def ping(self) -> bool:
        """Return whether the store root exists (creating it if needed) and is writable."""
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            return self._root.is_dir() and os.access(self._root, os.W_OK)
        except OSError:
            return False


def _sha256_of_file(path: Path) -> str:
    from trendsmapp.hashing import sha256_file

    return sha256_file(path)
