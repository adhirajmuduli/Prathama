"""Tests for streaming hashing and canonical hashing."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

from trendsmapp.hashing import (
    canonical_json_hash,
    combine_hashes,
    hashes_match,
    is_sha256_hex,
    sha256_bytes,
    sha256_file,
    sha256_stream,
    sha256_text,
)


def test_sha256_bytes_matches_hashlib() -> None:
    payload = b"trendsmapp"
    assert sha256_bytes(payload) == hashlib.sha256(payload).hexdigest()


def test_sha256_text_is_utf8_encoded() -> None:
    assert sha256_text("é") == sha256_bytes("é".encode())


def test_sha256_stream_reads_in_bounded_chunks(tmp_path: Path) -> None:
    payload = b"x" * (1024 * 32)
    stream = io.BytesIO(payload)
    digest = sha256_stream(stream, chunk_size=1024)
    assert digest == hashlib.sha256(payload).hexdigest()


def test_sha256_file_matches_streamed_digest(tmp_path: Path) -> None:
    path = tmp_path / "artifact.bin"
    payload = b"payload" * 1000
    path.write_bytes(payload)
    assert sha256_file(path) == hashlib.sha256(payload).hexdigest()


def test_canonical_json_hash_is_order_independent() -> None:
    left = canonical_json_hash({"b": 1, "a": {"d": 4, "c": 3}})
    right = canonical_json_hash({"a": {"c": 3, "d": 4}, "b": 1})
    assert left == right


def test_canonical_json_hash_changes_with_content() -> None:
    assert canonical_json_hash({"a": 1}) != canonical_json_hash({"a": 2})


def test_is_sha256_hex_rejects_malformed_digests() -> None:
    assert is_sha256_hex("a" * 64)
    assert not is_sha256_hex("A" * 64)
    assert not is_sha256_hex("a" * 63)
    assert not is_sha256_hex(None)


def test_hashes_match_compares_valid_digests_only() -> None:
    digest = "b" * 64
    assert hashes_match(digest, digest)
    assert not hashes_match(digest, "c" * 64)
    assert not hashes_match("not-a-digest", digest)


def test_combine_hashes_is_order_sensitive() -> None:
    first = "a" * 64
    second = "b" * 64
    assert combine_hashes([first, second]) != combine_hashes([second, first])
