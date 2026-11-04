"""Streaming SHA-256 hashing, canonical hashing, and hash comparison.

Every artifact stored by the application is addressed by the SHA-256 of its
exact bytes. The helpers here are the only sanctioned way to compute those
digests so that streaming and in-memory paths cannot diverge.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Protocol

from trendsmapp.serialization import canonical_json_bytes

__all__ = [
    "DEFAULT_CHUNK_SIZE",
    "ReadableBinaryStream",
    "canonical_json_hash",
    "hashes_match",
    "is_sha256_hex",
    "sha256_bytes",
    "sha256_file",
    "sha256_stream",
    "sha256_text",
]

DEFAULT_CHUNK_SIZE = 1024 * 1024

_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


class ReadableBinaryStream(Protocol):
    """The minimal readable-binary interface required for streaming hashes."""

    def read(self, size: int = -1, /) -> bytes:
        """Read up to ``size`` bytes and return them."""
        ...


def sha256_bytes(payload: bytes) -> str:
    """Return the lowercase hexadecimal SHA-256 digest of ``payload``."""
    return hashlib.sha256(payload).hexdigest()


def sha256_text(text: str) -> str:
    """Return the lowercase hexadecimal SHA-256 digest of UTF-8 encoded ``text``."""
    return sha256_bytes(text.encode("utf-8"))


def sha256_stream(stream: ReadableBinaryStream, *, chunk_size: int = DEFAULT_CHUNK_SIZE) -> str:
    """Return the SHA-256 digest of a binary stream, read in bounded chunks."""
    if chunk_size <= 0:
        raise ValueError("The chunk size must be positive.")
    digest = hashlib.sha256()
    while True:
        chunk = stream.read(chunk_size)
        if not chunk:
            break
        digest.update(chunk)
    return digest.hexdigest()


def sha256_file(path: Path, *, chunk_size: int = DEFAULT_CHUNK_SIZE) -> str:
    """Return the SHA-256 digest of a file's exact bytes."""
    with path.open("rb") as handle:
        return sha256_stream(handle, chunk_size=chunk_size)


def canonical_json_hash(value: Any) -> str:
    """Return the SHA-256 digest of the canonical JSON encoding of ``value``."""
    return sha256_bytes(canonical_json_bytes(value))


def is_sha256_hex(value: object) -> bool:
    """Return whether ``value`` is a lowercase hexadecimal SHA-256 digest."""
    return isinstance(value, str) and bool(_SHA256_HEX.fullmatch(value))


def hashes_match(expected: str, actual: str) -> bool:
    """Compare two digests in constant time."""
    if not is_sha256_hex(expected) or not is_sha256_hex(actual):
        return False
    return hmac.compare_digest(expected, actual)


def combine_hashes(digests: Iterable[str]) -> str:
    """Return a stable digest over an ordered collection of digests."""
    digest = hashlib.sha256()
    for item in digests:
        digest.update(item.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()
