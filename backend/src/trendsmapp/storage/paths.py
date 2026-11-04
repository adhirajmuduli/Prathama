"""Content-addressed key construction with traversal rejection.

Storage keys are derived from identifiers and hashes, never from a
client-supplied path. Every key is validated before it reaches an adapter:
absolute paths, parent traversal, empty segments, control characters, and
Windows-reserved characters are rejected.
"""

from __future__ import annotations

import re
from typing import Final

from trendsmapp.errors import ValidationError

__all__ = [
    "ALLOWED_ARTIFACT_KINDS",
    "build_artifact_key",
    "build_raw_upload_key",
    "build_upload_part_key",
    "safe_filename",
    "validate_storage_key",
]

ALLOWED_ARTIFACT_KINDS: Final[tuple[str, ...]] = (
    "artifacts",
    "uploads",
    "datasets",
    "runs",
    "exports",
    "boundaries",
)

_SEGMENT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_FILENAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_RESERVED_WINDOWS_NAMES: Final[frozenset[str]] = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{number}" for number in range(1, 10)),
        *(f"lpt{number}" for number in range(1, 10)),
    }
)


def validate_storage_key(key: str) -> str:
    """Validate a storage key and return it unchanged."""
    if not isinstance(key, str) or not key:
        raise ValidationError("A storage key is required.")
    if key.startswith("/") or key.startswith("\\"):
        raise ValidationError("A storage key must be relative.", details={"key": key})
    if "\\" in key:
        raise ValidationError("A storage key must use forward slashes.", details={"key": key})
    if any(ord(character) < 32 for character in key):
        raise ValidationError("A storage key must not contain control characters.")
    segments = key.split("/")
    if any(segment in {"", ".", ".."} for segment in segments):
        raise ValidationError(
            "A storage key must not contain empty or traversal segments.",
            details={"key": key},
        )
    for segment in segments:
        if _SEGMENT_PATTERN.fullmatch(segment) is None:
            raise ValidationError(
                f"Storage key segment '{segment}' contains unsupported characters.",
                details={"key": key},
            )
    return key


def safe_filename(name: str) -> str:
    """Return a filesystem- and object-store-safe filename."""
    if not isinstance(name, str):
        raise ValidationError("A filename is required.")
    trimmed = name.strip().replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", trimmed).strip("._")
    if not cleaned:
        raise ValidationError("The filename does not contain usable characters.")
    stem = cleaned.split(".", 1)[0].lower()
    if stem in _RESERVED_WINDOWS_NAMES:
        cleaned = f"_{cleaned}"
    return cleaned


def build_artifact_key(kind: str, sha256: str, filename: str) -> str:
    """Build the content-addressed key of a stored artifact."""
    if kind not in ALLOWED_ARTIFACT_KINDS:
        raise ValidationError(
            f"Unsupported artifact kind '{kind}'.",
            details={"allowed": list(ALLOWED_ARTIFACT_KINDS)},
        )
    if not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise ValidationError("An artifact key requires a SHA-256 digest.")
    return validate_storage_key(f"{kind}/{sha256[:2]}/{sha256}/{safe_filename(filename)}")


def build_raw_upload_key(upload_id: str, sha256: str, filename: str) -> str:
    """Build the key of a completed raw upload."""
    if not re.fullmatch(r"upl_[0-9a-f]{32}", upload_id):
        raise ValidationError("An upload identifier is required.")
    if not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise ValidationError("An upload key requires a SHA-256 digest.")
    return validate_storage_key(f"uploads/{upload_id}/{sha256}/{safe_filename(filename)}")


def build_upload_part_key(upload_id: str, part_number: int) -> str:
    """Build the key of one uploaded part."""
    if not re.fullmatch(r"upl_[0-9a-f]{32}", upload_id):
        raise ValidationError("An upload identifier is required.")
    if part_number < 1 or part_number > 100_000:
        raise ValidationError(
            "The part number is out of range.", details={"part_number": part_number}
        )
    return validate_storage_key(f"uploads/{upload_id}/parts/{part_number:05d}")
