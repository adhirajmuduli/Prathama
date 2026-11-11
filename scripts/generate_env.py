#!/usr/bin/env python3
"""Generate a local `.env` from `.env.example` with random secret values.

Every line whose value looks like a placeholder (``your-…``, ``ci-…``,
``re_your_…``) and whose key names a credential (PASSWORD, SECRET, TOKEN,
API_KEY, …) is replaced with a freshly generated ``secrets.token_urlsafe``
value. Non-secret placeholders (URLs, origins, numbers) are left as-is.
Existing `.env` is never overwritten unless ``--force`` is given.

Usage: python scripts/generate_env.py [--force] [--example PATH] [--output PATH]
"""

from __future__ import annotations

import argparse
import re
import secrets
import sys
from pathlib import Path

_SECRET_KEY_RE = re.compile(r"(PASSWORD|SECRET|TOKEN|API_KEY)", re.IGNORECASE)
_PLACEHOLDER_RE = re.compile(r"(your-|ci-ephemeral|re_your_)", re.IGNORECASE)


def generate(example: Path, output: Path, force: bool) -> int:
    """Write ``output`` with random values for credential placeholders."""
    if output.exists() and not force:
        print(f"{output} already exists; use --force to overwrite", file=sys.stderr)
        return 1
    lines_out: list[str] = []
    filled = 0
    for line in example.read_text(encoding="utf-8").splitlines():
        stripped = line.lstrip("#").strip()
        if stripped and "=" in stripped:
            key, _, value = stripped.partition("=")
            if _SECRET_KEY_RE.search(key) and _PLACEHOLDER_RE.search(value):
                # Randomize credential placeholders even when the example line
                # is commented out: the generated .env carries the real value.
                lines_out.append(f"{key}={secrets.token_urlsafe(32)}")
                filled += 1
                continue
        lines_out.append(line)
    output.write_text("\n".join(lines_out) + "\n", encoding="utf-8")
    print(f"wrote {output} ({filled} credentials randomized; review before use)")
    print("next: never commit .env — it is gitignored; set production values in")
    print("the platform's secret manager (Netlify/Render/Actions secrets).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="overwrite an existing .env")
    parser.add_argument("--example", type=Path, default=Path(".env.example"))
    parser.add_argument("--output", type=Path, default=Path(".env"))
    args = parser.parse_args()
    return generate(args.example, args.output, args.force)


if __name__ == "__main__":
    sys.exit(main())
