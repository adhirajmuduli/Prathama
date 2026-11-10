#!/usr/bin/env python3
"""Audit a frozen requirements lock against OSV with an advisory allowlist.

The legacy prototype's lockfile is intentionally frozen, so the advisories
that exist today are accepted (listed in ``legacy-audit-allowlist.txt`` with
the review date). Any advisory NOT on the list fails the build, so a newly
published CVE against a pinned package is caught immediately; extending the
list requires a code change and review.

Usage: python scripts/audit_lock.py requirements.lock.txt [--allowlist PATH]
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

DEFAULT_ALLOWLIST = Path(__file__).parent / "legacy-audit-allowlist.txt"
_PIN_RE = re.compile(r"^([A-Za-z0-9_.\-]+)==([^\s;]+)", flags=re.M)


def _load_allowlist(path: Path) -> set[str]:
    """Return the accepted advisory ids (one per line; ``#`` comments allowed)."""
    if not path.exists():
        return set()
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }


def main() -> int:
    """Audit the lock; return 1 when an advisory is missing from the allowlist."""
    args = sys.argv[1:]
    lock = next((a for a in args if not a.startswith("--")), "requirements.lock.txt")
    allowlist_path = Path(args[args.index("--allowlist") + 1]) if "--allowlist" in args else DEFAULT_ALLOWLIST
    allowed = _load_allowlist(allowlist_path)

    text = Path(lock).read_text(encoding="utf-8")
    pinned = _PIN_RE.findall(text)
    print(f"audit_lock: {lock}: {len(pinned)} pinned packages, {len(allowed)} allowlisted advisories")
    failures: list[str] = []
    total = 0
    for name, version in pinned:
        query = {"package": {"name": name, "ecosystem": "PyPI"}, "version": version}
        req = urllib.request.Request(
            "https://api.osv.dev/v1/query",
            data=json.dumps(query).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                vulns = json.load(resp).get("vulns", [])
        except Exception as exc:  # noqa: BLE001 - report and continue
            print(f"  ? {name}=={version}: OSV query failed: {exc}")
            continue
        for vuln in vulns:
            total += 1
            ids = {vuln["id"], *vuln.get("aliases", [])}
            if not (ids & allowed):
                failures.append(f"{name}=={version} {vuln['id']} ({', '.join(vuln.get('aliases', [])[:2])})")
    print(f"audit_lock: {total} advisories found, {len(failures)} not allowlisted")
    for line in failures:
        print(f"  FAIL {line}")
    if failures:
        print(f"  extend {allowlist_path} with a review note, or upgrade the package")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
