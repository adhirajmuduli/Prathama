"""Tests for the storage adapters and key construction."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from trendsmapp.errors import StorageError, ValidationError
from trendsmapp.hashing import sha256_bytes
from trendsmapp.storage.local import LocalObjectStore
from trendsmapp.storage.paths import (
    build_artifact_key,
    build_raw_upload_key,
    build_upload_part_key,
    safe_filename,
    validate_storage_key,
)


def test_local_store_round_trips_bytes(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path / "objects")
    payload = b"trendsmapp"
    stored = store.put_bytes(
        "artifacts/aa/file.bin", payload, content_type="application/octet-stream"
    )
    assert stored.sha256 == sha256_bytes(payload)
    assert stored.size_bytes == len(payload)
    assert store.get_bytes("artifacts/aa/file.bin") == payload
    assert store.exists("artifacts/aa/file.bin")


def test_local_store_streams_and_verifies_size(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path / "objects")
    payload = b"streamed" * 1024
    stored = store.put_stream(
        "artifacts/bb/file.bin",
        io.BytesIO(payload),
        content_type="application/octet-stream",
        expected_size=len(payload),
    )
    assert stored.sha256 == sha256_bytes(payload)
    with store.open_stream("artifacts/bb/file.bin") as stream:
        assert stream.read() == payload


def test_local_store_rejects_a_wrong_declared_size(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path / "objects")
    with pytest.raises(StorageError):
        store.put_stream(
            "artifacts/bb/file.bin",
            io.BytesIO(b"payload"),
            content_type="application/octet-stream",
            expected_size=999,
        )
    assert not store.exists("artifacts/bb/file.bin")


def test_local_store_lists_and_deletes(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path / "objects")
    store.put_bytes("runs/run_1/a.bin", b"a", content_type="application/octet-stream")
    store.put_bytes("runs/run_1/b.bin", b"b", content_type="application/octet-stream")
    assert sorted(store.list_prefix("runs/run_1")) == ["runs/run_1/a.bin", "runs/run_1/b.bin"]
    store.delete("runs/run_1/a.bin")
    assert not store.exists("runs/run_1/a.bin")


def test_local_store_reports_missing_objects(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path / "objects")
    with pytest.raises(StorageError):
        store.get_bytes("runs/missing.bin")


def test_local_store_ping_reports_writable_root(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path / "objects")
    assert store.ping() is True


def test_storage_keys_reject_traversal_and_absolute_paths() -> None:
    for invalid in [
        "../escape",
        "/absolute",
        "runs/../../etc/passwd",
        "runs//double",
        "runs/./here",
    ]:
        with pytest.raises(ValidationError):
            validate_storage_key(invalid)


def test_safe_filename_strips_directories_and_reserved_names() -> None:
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename("con.csv") == "_con.csv"
    with pytest.raises(ValidationError):
        safe_filename("   ")


def test_artifact_keys_are_content_addressed() -> None:
    digest = "b" * 64
    key = build_artifact_key("artifacts", digest, "surface.png")
    assert key == f"artifacts/bb/{digest}/surface.png"


def test_upload_keys_require_valid_identifiers() -> None:
    upload_id = "upl_" + "a" * 32
    digest = "c" * 64
    assert build_raw_upload_key(upload_id, digest, "data.csv") == (
        f"uploads/{upload_id}/{digest}/data.csv"
    )
    assert build_upload_part_key(upload_id, 3) == f"uploads/{upload_id}/parts/00003"
    with pytest.raises(ValidationError):
        build_upload_part_key("not-an-upload-id", 1)
    with pytest.raises(ValidationError):
        build_artifact_key("artifacts", "not-a-digest", "surface.png")
