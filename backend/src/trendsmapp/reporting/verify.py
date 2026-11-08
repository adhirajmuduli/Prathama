"""Verification of an export bundle: every checksum, every manifest entry.

Verification is pure and offline: it reads only the bundle bytes. A bundle is
valid only when every file listed in ``checksums.sha256`` matches its digest,
no listed file is missing, no unexpected file is present, the manifest parses,
and every artifact the manifest indexes matches the bytes stored under its
bundle path.
"""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass
from typing import Any

from trendsmapp.errors import ValidationError
from trendsmapp.hashing import hashes_match, is_sha256_hex, sha256_bytes
from trendsmapp.reporting.bundle import BUNDLE_SCHEMA_VERSION

__all__ = ["BundleVerification", "verify_bundle"]

_CHECKSUMS_NAME = "checksums.sha256"
_MANIFEST_NAME = "manifest.json"


@dataclass(frozen=True, slots=True)
class BundleVerification:
    """The outcome of verifying one bundle."""

    ok: bool
    checked_files: int
    mismatches: tuple[str, ...]
    missing: tuple[str, ...]
    unexpected: tuple[str, ...]
    manifest: dict[str, Any]


def verify_bundle(payload: bytes) -> BundleVerification:
    """Verify every checksum and contract of a bundle; raise when not a ZIP."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise ValidationError(
            "The export bundle is not a valid ZIP archive.",
            details={"reason": "not_a_zip"},
        ) from exc
    with archive:
        names = set(archive.namelist())
        for required in (_MANIFEST_NAME, _CHECKSUMS_NAME):
            if required not in names:
                raise ValidationError(
                    f"The export bundle is missing '{required}'.",
                    details={"reason": "missing_member", "member": required},
                )
        manifest = _read_manifest(archive)
        listed = _read_checksums(archive)

        mismatches: list[str] = []
        missing: list[str] = []
        for name, expected in listed:
            if name not in names:
                missing.append(name)
                continue
            actual = sha256_bytes(archive.read(name))
            if not hashes_match(expected, actual):
                mismatches.append(name)
        unexpected = sorted(names - {name for name, _ in listed} - {_CHECKSUMS_NAME})

        manifest_mismatches = _verify_manifest_artifacts(manifest, archive, names)
        mismatches.extend(manifest_mismatches)

        ok = not mismatches and not missing and not unexpected
        return BundleVerification(
            ok=ok,
            checked_files=len(listed),
            mismatches=tuple(sorted(mismatches)),
            missing=tuple(sorted(missing)),
            unexpected=tuple(unexpected),
            manifest=manifest,
        )


def _read_manifest(archive: zipfile.ZipFile) -> dict[str, Any]:
    """Parse and version-check the bundle manifest."""
    document = json.loads(archive.read(_MANIFEST_NAME).decode("utf-8"))
    if not isinstance(document, dict):
        raise ValidationError(
            "The bundle manifest must be a JSON mapping.",
            details={"reason": "invalid_manifest"},
        )
    version = document.get("schema_version")
    if version != BUNDLE_SCHEMA_VERSION:
        raise ValidationError(
            f"The bundle manifest schema version '{version}' is not supported; "
            f"expected '{BUNDLE_SCHEMA_VERSION}'.",
            details={"reason": "unsupported_bundle_schema", "found": version},
        )
    return document


def _read_checksums(archive: zipfile.ZipFile) -> list[tuple[str, str]]:
    """Parse ``checksums.sha256`` into ``(name, digest)`` pairs."""
    entries: list[tuple[str, str]] = []
    text = archive.read(_CHECKSUMS_NAME).decode("utf-8")
    for line in text.splitlines():
        if not line.strip():
            continue
        digest, separator, name = line.partition("  ")
        if not separator or not is_sha256_hex(digest) or not name:
            raise ValidationError(
                "The bundle checksums file is malformed.",
                details={"reason": "invalid_checksums", "line": line},
            )
        entries.append((name, digest))
    return entries


def _verify_manifest_artifacts(
    manifest: dict[str, Any], archive: zipfile.ZipFile, names: set[str]
) -> list[str]:
    """Check every manifest artifact entry against the bytes at its bundle path."""
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        return []
    mismatches: list[str] = []
    for entry in artifacts:
        if not isinstance(entry, dict):
            continue
        path = entry.get("bundle_path")
        expected = entry.get("sha256")
        if not isinstance(path, str) or not isinstance(expected, str):
            continue
        if path not in names:
            mismatches.append(path)
            continue
        if not hashes_match(expected, sha256_bytes(archive.read(path))):
            mismatches.append(path)
    return mismatches
