#!/usr/bin/env python3
"""Fail when any tracked text file has CRLF in its git index blob.

`.gitattributes` declares `* text=auto eol=lf`, so checkouts must be LF on
every platform. A resource whose recorded provenance digest was taken over
CRLF bytes passes locally (Windows worktree) but fails on Linux CI, which is
exactly the class of bug this guard prevents: provenance and fixture digests
must be computed over the LF bytes that every runner checks out.
"""

from __future__ import annotations

import subprocess
import sys


def main() -> int:
    """Return 0 when every tracked file is LF-normalized in the index."""
    listing = subprocess.run(
        ["git", "ls-files", "--eol"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    bad: list[str] = []
    for line in listing.splitlines():
        # Format: "i/crlf w/lf attr/... path" or "i/lf w/lf ..."
        parts = line.split("\t", 1)
        if len(parts) != 2:
            continue
        index_eol = parts[0].split()[0]
        path = parts[1]
        if index_eol == "i/crlf":
            bad.append(path)
    if bad:
        print("check_text_normalization: files with CRLF in the git index:")
        for path in bad:
            print(f"  {path}")
        print("run `git add --renormalize <path>` and commit the LF blob")
        return 1
    print("check_text_normalization: all tracked files are LF in the index")
    return 0


if __name__ == "__main__":
    sys.exit(main())
