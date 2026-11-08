"""The run manifest: the complete reproducibility record of one export bundle.

Every manifest records the dataset hash, boundary hash, recipe hash, software
version, dependency-lock hash, random seed, runtime environment, and the hash
of every output. The manifest is built from values already persisted on the
run row and artifact rows, so it never re-derives science.
"""

from __future__ import annotations

import platform
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from trendsmapp.contracts.versions import APPLICATION_VERSION, ARTIFACT_SCHEMA_VERSION
from trendsmapp.hashing import canonical_json_hash, sha256_file

__all__ = [
    "MANIFEST_SCHEMA_VERSION",
    "build_manifest",
    "dependency_lock_sha256",
    "manifest_sha256",
    "runtime_environment",
]

#: Version of the manifest document inside an export bundle.
MANIFEST_SCHEMA_VERSION: Final[str] = "1.0.0"


def runtime_environment() -> dict[str, str]:
    """Capture the interpreter and platform of the exporting process."""
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "application_version": APPLICATION_VERSION,
    }


def dependency_lock_sha256(start: Path | None = None) -> str | None:
    """Return the SHA-256 of the backend ``uv.lock``, or ``None`` when not shipped.

    The lockfile is located by walking upward from ``start`` (default: this
    file). A container image that does not ship the lockfile records an
    explicit absence instead of inventing a value.
    """
    here = start or Path(__file__).resolve()
    for parent in (here, *here.parents):
        candidate = parent / "uv.lock"
        if candidate.is_file():
            return sha256_file(candidate)
    return None


def build_manifest(
    *,
    run: Mapping[str, Any],
    dataset_version: Mapping[str, Any],
    artifacts: Sequence[Mapping[str, Any]],
    tables: Mapping[str, str],
    methods: Mapping[str, Any],
    generated_at: datetime,
    lock_sha256: str | None = None,
) -> dict[str, Any]:
    """Build the manifest document of one run.

    ``artifacts`` entries must carry ``artifact_id``, ``kind``, ``sha256``,
    ``size_bytes``, ``content_type``, and ``bundle_path``. ``tables`` maps a
    table file name to its SHA-256.
    """
    manifest: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        "application_version": APPLICATION_VERSION,
        "run_id": run["id"],
        "run_status": run.get("status"),
        "dataset_version_id": dataset_version["id"],
        "dataset_sha256": dataset_version.get("normalized_sha256"),
        "boundary_sha256": run.get("boundary_sha256"),
        "recipe_hash": run.get("recipe_hash"),
        "recipe": run.get("recipe"),
        "seed": run.get("seed"),
        "created_at": _iso(run.get("created_at")),
        "finished_at": _iso(run.get("finished_at")),
        "generated_at": _iso(generated_at),
        "environment": runtime_environment(),
        "dependency_lock": {
            "file": "backend/uv.lock",
            "sha256": lock_sha256,
            "available": lock_sha256 is not None,
        },
        "artifacts": [
            {
                "artifact_id": entry["artifact_id"],
                "kind": entry["kind"],
                "sha256": entry["sha256"],
                "size_bytes": entry["size_bytes"],
                "content_type": entry["content_type"],
                "bundle_path": entry["bundle_path"],
            }
            for entry in artifacts
        ],
        "tables": dict(sorted(tables.items())),
        "methods": dict(methods),
        "reproduction": {
            "command": "trendsmapp reproduce <bundle.zip>",
            "verifies": "every SHA-256 in checksums.sha256 and the manifest artifact index",
        },
    }
    return manifest


def manifest_sha256(manifest: Mapping[str, Any]) -> str:
    """Return the canonical-JSON SHA-256 of a manifest document."""
    return canonical_json_hash(manifest)


def _iso(value: Any) -> str | None:
    """Return an ISO 8601 string for a datetime-like value."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
