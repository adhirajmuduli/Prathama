"""Verify that the compatibility note matches the committed contract snapshot.

The OpenAPI snapshot is the public contract of the API. A change to it must be
accompanied by an updated compatibility note, so that a reviewer can read what
changed and why. This script compares the digest recorded in the note with the
digest of the snapshot and fails when they differ.

Usage::

    python scripts/check_contract_compatibility.py
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_PATH = REPOSITORY_ROOT / "contracts" / "openapi.v1.json"
NOTE_PATH = REPOSITORY_ROOT / "contracts" / "COMPATIBILITY.md"

DIGEST_PATTERN = re.compile(r"OpenAPI snapshot SHA-256:\s*`([0-9a-f]{64})`")


def sha256_of(path: Path) -> str:
    """Return the SHA-256 digest of a file's exact bytes."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    """Run the check and report the findings."""
    if not SNAPSHOT_PATH.exists():
        print(f"check_contract_compatibility: {SNAPSHOT_PATH} is missing")
        return 1
    if not NOTE_PATH.exists():
        print(f"check_contract_compatibility: {NOTE_PATH} is missing")
        return 1

    expected = sha256_of(SNAPSHOT_PATH)
    note = NOTE_PATH.read_text(encoding="utf-8")
    match = DIGEST_PATTERN.search(note)
    if match is None:
        print(
            "check_contract_compatibility: the compatibility note does not record "
            "the OpenAPI snapshot digest"
        )
        return 1

    recorded = match.group(1)
    if recorded != expected:
        print(
            "check_contract_compatibility: the compatibility note records a stale "
            f"digest ({recorded}); the snapshot digest is {expected}"
        )
        return 1

    print("check_contract_compatibility: the compatibility note matches the snapshot")
    return 0


if __name__ == "__main__":
    sys.exit(main())
