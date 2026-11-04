from __future__ import annotations

import logging
import re
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Only application-generated artifacts ({uuid4().hex}_{name}) are eligible for
# sweeping; anything else placed in managed directories is never deleted.
RUNTIME_ARTIFACT_PATTERN = re.compile(r"^[0-9a-f]{32}_.+$")


def purge_expired_files(directories: tuple[Path, ...], ttl_hours: float) -> int:
    """Delete expired application-generated files. A non-positive TTL disables sweeping."""
    if ttl_hours <= 0:
        return 0
    cutoff = time.time() - ttl_hours * 3600
    removed = 0
    for directory in directories:
        if not directory.is_dir():
            continue
        for candidate in sorted(directory.iterdir()):
            try:
                if not RUNTIME_ARTIFACT_PATTERN.match(candidate.name):
                    continue
                if not candidate.is_file() or candidate.stat().st_mtime >= cutoff:
                    continue
                candidate.unlink()
                removed += 1
            except OSError as exc:
                logger.warning("Could not remove stale file %s: %s", candidate, exc)
    return removed


def remove_replaced_upload(value: str | None, directory: Path) -> None:
    """Best-effort delete of a previous session file to bound disk use.

    Only the file's basename under the given managed directory is considered,
    so a hostile or stale session value cannot address other paths.
    """
    if not value:
        return
    candidate = directory / Path(value).name
    try:
        candidate.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("Could not remove replaced upload %s: %s", candidate, exc)
