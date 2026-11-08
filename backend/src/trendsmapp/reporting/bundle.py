"""Deterministic ZIP export bundles.

A bundle is built only from already-hashed artifacts, so building the same run
twice produces byte-identical output: fixed member timestamps, sorted member
names, fixed compression level, and a ``checksums.sha256`` manifest of every
member except itself.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Mapping, Sequence
from typing import Any, Final

from trendsmapp.hashing import sha256_bytes
from trendsmapp.serialization import canonical_json_bytes

__all__ = ["BUNDLE_SCHEMA_VERSION", "build_bundle", "bundle_sha256", "read_bundle_manifest"]

#: Version of the bundle container format.
BUNDLE_SCHEMA_VERSION: Final[str] = "1.0.0"

#: Fixed member timestamp so identical inputs produce identical ZIP bytes.
_FIXED_DATE_TIME: Final[tuple[int, int, int, int, int, int]] = (1980, 1, 1, 0, 0, 0)

_COMPRESSION_LEVEL: Final[int] = 6


def build_bundle(
    *,
    manifest: Mapping[str, Any],
    files: Sequence[tuple[str, bytes]],
) -> bytes:
    """Build the deterministic ZIP bytes of one export bundle.

    ``files`` are ``(archive_name, payload)`` pairs; ``manifest.json`` and
    ``checksums.sha256`` are added by this function and must not appear in
    ``files``.
    """
    for name, _payload in files:
        if name in {"manifest.json", "checksums.sha256"}:
            raise ValueError(f"'{name}' is reserved for the bundle itself.")
    entries = sorted(files, key=lambda item: item[0])
    manifest_bytes = canonical_json_bytes(manifest)
    members: list[tuple[str, bytes]] = [("manifest.json", manifest_bytes), *entries]

    buffer = io.BytesIO()
    checksum_lines: list[str] = []
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in members:
            _write_member(archive, name, payload)
            checksum_lines.append(f"{sha256_bytes(payload)}  {name}")
        _write_member(
            archive, "checksums.sha256", ("\n".join(checksum_lines) + "\n").encode("utf-8")
        )
    return buffer.getvalue()


def bundle_sha256(payload: bytes) -> str:
    """Return the SHA-256 of a bundle's exact bytes."""
    return sha256_bytes(payload)


def read_bundle_manifest(payload: bytes) -> dict[str, Any]:
    """Return the manifest document stored inside a bundle."""
    import json

    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        document = json.loads(archive.read("manifest.json").decode("utf-8"))
    if not isinstance(document, dict):
        raise ValueError("manifest.json must contain a mapping.")
    return document


def _write_member(archive: zipfile.ZipFile, name: str, payload: bytes) -> None:
    """Write one member with a fixed timestamp and permissions."""
    info = zipfile.ZipInfo(name, date_time=_FIXED_DATE_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    archive.writestr(info, payload, compresslevel=_COMPRESSION_LEVEL)
