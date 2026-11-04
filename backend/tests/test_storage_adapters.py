"""Storage adapter tests for the local, S3-compatible, and factory layers."""

from __future__ import annotations

import io
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from trendsmapp.errors import ConfigurationError, StorageError, ValidationError
from trendsmapp.hashing import sha256_bytes
from trendsmapp.settings import Settings
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


class _FakeS3Client:
    """An in-memory stand-in for the boto3 S3 client."""

    def __init__(self) -> None:
        self.objects: dict[str, dict[str, Any]] = {}
        self.failures: set[str] = set()

    def put_object(
        self,
        *,
        Bucket: str,
        Key: str,
        Body: bytes,
        ContentType: str,
        Metadata: dict[str, str],
    ) -> None:
        if "put_object" in self.failures:
            raise RuntimeError("put_object failed")
        self.objects[Key] = {
            "body": Body,
            "content_type": ContentType,
            "metadata": dict(Metadata),
        }

    def upload_fileobj(
        self,
        fileobj: Any,
        bucket: str,
        key: str,
        ExtraArgs: dict[str, Any],
    ) -> None:
        if "upload_fileobj" in self.failures:
            raise RuntimeError("upload_fileobj failed")
        payload = fileobj.read()
        self.objects[key] = {
            "body": payload,
            "content_type": ExtraArgs["ContentType"],
            "metadata": dict(ExtraArgs["Metadata"]),
        }

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        if "get_object" in self.failures:
            raise RuntimeError("get_object failed")
        if Key not in self.objects:
            raise KeyError(Key)
        stored = self.objects[Key]
        return {
            "Body": io.BytesIO(stored["body"]),
            "Metadata": dict(stored["metadata"]),
        }

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        if "head_object" in self.failures:
            raise RuntimeError("head_object failed")
        if Key not in self.objects:
            raise KeyError(Key)
        stored = self.objects[Key]
        return {
            "ContentLength": len(stored["body"]),
            "ContentType": stored["content_type"],
            "Metadata": dict(stored["metadata"]),
        }

    def delete_object(self, *, Bucket: str, Key: str) -> None:
        if "delete_object" in self.failures:
            raise RuntimeError("delete_object failed")
        self.objects.pop(Key, None)

    def get_paginator(self, operation: str) -> Any:
        if operation != "list_objects_v2":
            raise RuntimeError(f"unsupported operation: {operation}")
        return self

    def paginate(self, *, Bucket: str, Prefix: str) -> Iterator[dict[str, Any]]:
        if "list_objects_v2" in self.failures:
            raise RuntimeError("list_objects_v2 failed")
        contents = [{"Key": key} for key in sorted(self.objects) if key.startswith(Prefix)]
        yield {"Contents": contents}

    def head_bucket(self, *, Bucket: str) -> None:
        if "head_bucket" in self.failures:
            raise RuntimeError("head_bucket failed")


def test_s3_store_requires_a_bucket() -> None:
    with pytest.raises(StorageError):
        S3ObjectStore("", _FakeS3Client())


def test_s3_store_round_trips_objects_and_records_checksums() -> None:
    client = _FakeS3Client()
    store = S3ObjectStore("trendsmapp", client)
    payload = b"canonical observations"

    stored = store.put_bytes("datasets/aa/data.parquet", payload, content_type="application/x")
    assert stored.sha256 == sha256_bytes(payload)
    assert stored.size_bytes == len(payload)
    assert store.get_bytes("datasets/aa/data.parquet") == payload
    assert store.exists("datasets/aa/data.parquet") is True

    head = store.head("datasets/aa/data.parquet")
    assert head.sha256 == sha256_bytes(payload)
    assert head.content_type == "application/x"

    with store.open_stream("datasets/aa/data.parquet") as handle:
        assert handle.read() == payload

    store.delete("datasets/aa/data.parquet")
    assert store.exists("datasets/aa/data.parquet") is False
    assert store.ping() is True


def test_s3_store_applies_a_key_prefix() -> None:
    client = _FakeS3Client()
    store = S3ObjectStore("trendsmapp", client, key_prefix="production")
    store.put_bytes("datasets/aa/data.parquet", b"payload", content_type="application/x")
    assert "production/datasets/aa/data.parquet" in client.objects
    assert list(store.list_prefix("datasets")) == ["datasets/aa/data.parquet"]


def test_s3_store_streams_uploads_and_verifies_the_declared_size() -> None:
    client = _FakeS3Client()
    store = S3ObjectStore("trendsmapp", client)
    stored = store.put_stream(
        "datasets/aa/large.parquet",
        io.BytesIO(b"streamed payload"),
        content_type="application/x",
        expected_size=16,
    )
    assert stored.sha256 == sha256_bytes(b"streamed payload")
    assert store.get_bytes("datasets/aa/large.parquet") == b"streamed payload"

    with pytest.raises(StorageError):
        store.put_stream(
            "datasets/aa/mismatch.parquet",
            io.BytesIO(b"short"),
            content_type="application/x",
            expected_size=99,
        )


def test_s3_store_detects_a_corrupted_object() -> None:
    client = _FakeS3Client()
    store = S3ObjectStore("trendsmapp", client)
    store.put_bytes("datasets/aa/data.parquet", b"payload", content_type="application/x")
    client.objects["datasets/aa/data.parquet"]["metadata"]["sha256"] = "0" * 64
    with pytest.raises(StorageError):
        store.get_bytes("datasets/aa/data.parquet")


def test_s3_store_translates_client_failures_into_storage_errors() -> None:
    client = _FakeS3Client()
    store = S3ObjectStore("trendsmapp", client)
    client.failures.add("put_object")
    with pytest.raises(StorageError):
        store.put_bytes("datasets/aa/data.parquet", b"payload", content_type="application/x")

    client.failures.clear()
    client.failures.add("get_object")
    with pytest.raises(StorageError):
        store.get_bytes("datasets/aa/data.parquet")
    with pytest.raises(StorageError):
        store.open_stream("datasets/aa/data.parquet")

    client.failures.clear()
    client.failures.add("head_object")
    with pytest.raises(StorageError):
        store.head("datasets/aa/data.parquet")
    assert store.exists("datasets/aa/data.parquet") is False

    client.failures.clear()
    client.failures.add("delete_object")
    with pytest.raises(StorageError):
        store.delete("datasets/aa/data.parquet")

    client.failures.clear()
    client.failures.add("list_objects_v2")
    with pytest.raises(StorageError):
        list(store.list_prefix("datasets"))

    client.failures.clear()
    client.failures.add("head_bucket")
    assert store.ping() is False

    client.failures.clear()
    client.failures.add("upload_fileobj")
    with pytest.raises(StorageError):
        store.put_stream(
            "datasets/aa/large.parquet",
            io.BytesIO(b"payload"),
            content_type="application/x",
        )


def test_local_store_round_trips_objects(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path / "objects")
    payload = b"canonical observations"
    stored = store.put_bytes("datasets/aa/data.parquet", payload, content_type="application/x")
    assert stored.sha256 == sha256_bytes(payload)
    assert store.get_bytes("datasets/aa/data.parquet") == payload
    assert store.exists("datasets/aa/data.parquet") is True
    assert store.head("datasets/aa/data.parquet").size_bytes == len(payload)
    with store.open_stream("datasets/aa/data.parquet") as handle:
        assert handle.read() == payload

    streamed = store.put_stream(
        "datasets/aa/streamed.parquet",
        io.BytesIO(b"streamed payload"),
        content_type="application/x",
        expected_size=16,
    )
    assert streamed.sha256 == sha256_bytes(b"streamed payload")

    with pytest.raises(StorageError):
        store.put_stream(
            "datasets/aa/mismatch.parquet",
            io.BytesIO(b"short"),
            content_type="application/x",
            expected_size=99,
        )

    assert sorted(store.list_prefix("datasets")) == [
        "datasets/aa/data.parquet",
        "datasets/aa/streamed.parquet",
    ]
    store.delete("datasets/aa/data.parquet")
    assert store.exists("datasets/aa/data.parquet") is False
    store.delete("datasets/aa/data.parquet")
    assert store.ping() is True
    assert store.root.is_dir()


def test_local_store_reports_missing_objects(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path / "objects")
    with pytest.raises(StorageError):
        store.get_bytes("datasets/aa/missing.parquet")
    with pytest.raises(StorageError):
        store.open_stream("datasets/aa/missing.parquet")
    with pytest.raises(StorageError):
        store.head("datasets/aa/missing.parquet")
    assert list(store.list_prefix("missing")) == []


def test_local_store_refuses_keys_outside_its_root(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path / "objects")
    with pytest.raises(ValidationError):
        store.get_bytes("../escape")
    with pytest.raises(StorageError):
        list(store.list_prefix("../escape"))


def test_storage_keys_are_validated_and_built_from_identifiers() -> None:
    assert validate_storage_key("datasets/aa/file.parquet") == "datasets/aa/file.parquet"
    with pytest.raises(ValidationError):
        validate_storage_key("")
    with pytest.raises(ValidationError):
        validate_storage_key("/absolute")
    with pytest.raises(ValidationError):
        validate_storage_key("windows\\path")
    with pytest.raises(ValidationError):
        validate_storage_key("control\x01character")
    with pytest.raises(ValidationError):
        validate_storage_key("double//segment")

    digest = "a" * 64
    assert build_artifact_key("datasets", digest, "observations.parquet") == (
        f"datasets/aa/{digest}/observations.parquet"
    )
    with pytest.raises(ValidationError):
        build_artifact_key("unknown", digest, "observations.parquet")
    with pytest.raises(ValidationError):
        build_artifact_key("datasets", "not-a-digest", "observations.parquet")

    upload_id = "upl_" + "b" * 32
    assert build_raw_upload_key(upload_id, digest, "observations.csv") == (
        f"uploads/{upload_id}/{digest}/observations.csv"
    )
    with pytest.raises(ValidationError):
        build_raw_upload_key("not-an-upload", digest, "observations.csv")
    with pytest.raises(ValidationError):
        build_raw_upload_key(upload_id, "not-a-digest", "observations.csv")

    assert build_upload_part_key(upload_id, 3) == f"uploads/{upload_id}/parts/00003"
    with pytest.raises(ValidationError):
        build_upload_part_key(upload_id, 0)
    with pytest.raises(ValidationError):
        build_upload_part_key(upload_id, 100_001)


def test_safe_filenames_are_restricted() -> None:
    assert safe_filename("Chilika observations.csv") == "Chilika_observations.csv"
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename("CON.csv") == "_CON.csv"
    assert safe_filename("report 2026.xlsx") == "report_2026.xlsx"
    with pytest.raises(ValidationError):
        safe_filename("...")
    with pytest.raises(ValidationError):
        safe_filename(123)  # type: ignore[arg-type]


def test_factory_selects_the_configured_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local_settings = Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}",
        object_store_backend="local",
        local_storage_root=tmp_path / "objects",
    )
    store = create_object_store(local_settings)
    assert isinstance(store, LocalObjectStore)

    s3_settings = Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}",
        object_store_backend="s3",
        s3_bucket="trendsmapp",
    )
    monkeypatch.setattr(
        "trendsmapp.storage.factory.create_s3_client", lambda _settings: _FakeS3Client()
    )
    assert isinstance(create_object_store(s3_settings), S3ObjectStore)

    without_bucket = s3_settings.model_copy(update={"s3_bucket": None})
    with pytest.raises(ConfigurationError):
        create_object_store(without_bucket)

    unsupported = local_settings.model_copy(update={"object_store_backend": "ftp"})
    with pytest.raises(ConfigurationError):
        create_object_store(unsupported)
