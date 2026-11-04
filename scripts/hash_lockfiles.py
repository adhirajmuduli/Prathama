"""Emit deterministic hashes for the dependency lockfiles.

A run manifest records the hash of the dependency lock so that a result can be
tied to the exact resolution that produced it. This script computes those
hashes and keeps them in a committed record, which lets CI detect a lockfile
change that was never reflected in the record.

Usage::

    python scripts/hash_lockfiles.py              # print the hashes
    python scripts/hash_lockfiles.py --write      # update the committed record
    python scripts/hash_lockfiles.py --check      # fail when the record is stale
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RECORD_PATH = REPOSITORY_ROOT / "contracts" / "lockfile-hashes.json"

LOCKFILES = (
    ("backend", REPOSITORY_ROOT / "backend" / "uv.lock"),
    ("frontend", REPOSITORY_ROOT / "frontend" / "pnpm-lock.yaml"),
)


def sha256_of(path: Path) -> str:
    """Return the SHA-256 digest of a file's exact bytes."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compute_hashes() -> dict[str, str]:
    """Return the digest of every lockfile that exists."""
    hashes: dict[str, str] = {}
    for name, path in LOCKFILES:
        if not path.exists():
            continue
        hashes[f"{name}/{path.name}"] = sha256_of(path)
    return hashes


def render(hashes: dict[str, str]) -> str:
    """Return the deterministic JSON representation of the hashes."""
    return json.dumps(hashes, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Run the requested mode."""
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="update the committed record")
    mode.add_argument("--check", action="store_true", help="fail when the record is stale")
    arguments = parser.parse_args(argv)

    hashes = compute_hashes()
    if not hashes:
        print("hash_lockfiles: no lockfile was found")
        return 1
    rendered = render(hashes)

    if arguments.write:
        RECORD_PATH.parent.mkdir(parents=True, exist_ok=True)
        RECORD_PATH.write_text(rendered, encoding="utf-8")
        print(f"hash_lockfiles: updated {RECORD_PATH.relative_to(REPOSITORY_ROOT)}")
        return 0

    if arguments.check:
        if not RECORD_PATH.exists():
            print(
                f"hash_lockfiles: {RECORD_PATH.relative_to(REPOSITORY_ROOT)} is missing; "
                "run 'python scripts/hash_lockfiles.py --write'"
            )
            return 1
        expected = RECORD_PATH.read_text(encoding="utf-8")
        if expected != rendered:
            print(
                "hash_lockfiles: the committed lockfile hashes are stale; "
                "run 'python scripts/hash_lockfiles.py --write'"
            )
            return 1
        print("hash_lockfiles: the committed lockfile hashes are current")
        return 0

    sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
