"""Object-store protocol and typed results.

The application stores every artifact through this protocol. The local
filesystem adapter is used for development and tests; the S3 adapter is used
in production. Both implementations are content addressed, immutable, and
verify the SHA-256 of every object they write.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import BinaryIO, Protocol, runtime_checkable

__all__ = ["ObjectStore", "StoredObject", "StoredObjectStream"]


@dataclass(frozen=True, slots=True)
class StoredObject:
    """The metadata of one stored object."""

    key: str
    sha256: str
    size_bytes: int
    content_type: str
    metadata: dict[str, str] = field(default_factory=dict)


class StoredObjectStream(AbstractContextManager["BinaryIO"]):
    """A readable binary stream over a stored object."""

    def __init__(self, stream: BinaryIO) -> None:
        self._stream = stream

    def __enter__(self) -> BinaryIO:
        return self._stream

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying stream."""
        close = getattr(self._stream, "close", None)
        if callable(close):
            close()


@runtime_checkable
class ObjectStore(Protocol):
    """The operations every object-store adapter must support."""

    def put_bytes(self, key: str, payload: bytes, *, content_type: str) -> StoredObject:
        """Store ``payload`` under ``key`` and return its metadata."""
        ...

    def put_stream(
        self,
        key: str,
        stream: BinaryIO,
        *,
        content_type: str,
        expected_size: int | None = None,
    ) -> StoredObject:
        """Store the contents of ``stream`` under ``key`` and return its metadata."""
        ...

    def get_bytes(self, key: str) -> bytes:
        """Return the full contents of the object stored under ``key``."""
        ...

    def open_stream(self, key: str) -> StoredObjectStream:
        """Return a readable stream over the object stored under ``key``."""
        ...

    def exists(self, key: str) -> bool:
        """Return whether an object exists under ``key``."""
        ...

    def head(self, key: str) -> StoredObject:
        """Return the metadata of the object stored under ``key``."""
        ...

    def delete(self, key: str) -> None:
        """Delete the object stored under ``key`` if it exists."""
        ...

    def list_prefix(self, prefix: str) -> Iterator[str]:
        """Return the keys of every object under ``prefix``."""
        ...

    def ping(self) -> bool:
        """Return whether the store is reachable and writable."""
        ...
