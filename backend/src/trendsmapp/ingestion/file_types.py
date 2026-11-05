"""Extension, container, and magic-byte validation for uploaded files.

The extension selects the reader; the first bytes must be consistent with that
reader. A ZIP renamed to ``.csv``, a text file renamed to ``.xlsx``, or a
Parquet file named ``.csv`` is rejected before any parser touches it, because a
mismatch means the upload is not the file the client claims to have sent.

The declared MIME type is advisory: browsers disagree about delimited text, so
an unexpected type becomes a recorded warning, while the authoritative checks
remain the extension and the content.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from trendsmapp.constants import ALLOWED_UPLOAD_EXTENSIONS, SUPPORTED_MIME_TYPES
from trendsmapp.domain.enums import FileFormat
from trendsmapp.errors import ValidationError

__all__ = [
    "PARQUET_MAGIC",
    "ZIP_MAGIC_PREFIXES",
    "FileTypeVerdict",
    "detect_format_from_magic",
    "format_for_extension",
    "inspect_file_type",
    "looks_like_text",
    "normalize_content_type",
    "normalized_extension",
]

#: The signatures of a ZIP container, which is what an ``.xlsx`` file is.
ZIP_MAGIC_PREFIXES: Final[tuple[bytes, ...]] = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")

#: The signature at both ends of a Parquet file.
PARQUET_MAGIC: Final[bytes] = b"PAR1"

#: Extensions that need a real parser instead of a text reader. The legacy
#: binary ``.xls`` format is deliberately absent.
_EXTENSION_FORMATS: Final[dict[str, FileFormat]] = {
    ".csv": FileFormat.CSV,
    ".tsv": FileFormat.TSV,
    ".xlsx": FileFormat.XLSX,
    ".parquet": FileFormat.PARQUET,
}

_TEXT_FORMATS: Final[frozenset[FileFormat]] = frozenset({FileFormat.CSV, FileFormat.TSV})

#: Bytes below this value are control characters unless they are tab, newline,
#: or carriage return. A file that is mostly control characters is binary.
_CONTROL_BYTES: Final[frozenset[int]] = frozenset(
    value for value in range(32) if value not in {9, 10, 13}
)

#: The tolerated fraction of control characters in a text file. The value is
#: low because a legitimate delimited file contains none outside a quoted field.
_MAX_CONTROL_FRACTION: Final[float] = 0.02


@dataclass(frozen=True, slots=True)
class FileTypeVerdict:
    """The outcome of validating the name, type, and first bytes of an upload."""

    filename: str
    extension: str
    format: FileFormat
    magic_format: FileFormat | None
    content_type: str | None
    content_type_accepted: bool | None
    warnings: tuple[str, ...]


def normalized_extension(filename: str) -> str:
    """Return the lowercase extension of ``filename``, rejecting unknown ones."""
    if not isinstance(filename, str) or not filename.strip():
        raise ValidationError("A filename is required to determine the file format.")
    trimmed = filename.strip()
    if "/" in trimmed or "\\" in trimmed or ".." in trimmed:
        raise ValidationError(
            "The filename must be a plain name, not a path.",
            details={"filename": trimmed[:128]},
        )
    position = trimmed.rfind(".")
    if position <= 0 or position == len(trimmed) - 1:
        raise ValidationError(
            "The filename has no extension, so the file format cannot be determined.",
            details={"filename": trimmed, "supported_extension": sorted(ALLOWED_UPLOAD_EXTENSIONS)},
        )
    extension = trimmed[position:].lower()
    if extension not in ALLOWED_UPLOAD_EXTENSIONS:
        detail = (
            "The .xls format is not accepted; convert the file to .xlsx, .csv, or .parquet."
            if extension == ".xls"
            else "The extension is not supported."
        )
        raise ValidationError(
            detail,
            details={
                "filename": trimmed,
                "extension": extension,
                "supported_extension": sorted(ALLOWED_UPLOAD_EXTENSIONS),
            },
        )
    return extension


def format_for_extension(extension: str) -> FileFormat:
    """Return the file format a supported extension selects."""
    resolved = _EXTENSION_FORMATS.get(extension.lower())
    if resolved is None:
        raise ValidationError(
            f"'{extension}' is not a supported extension.",
            details={"supported_extension": sorted(ALLOWED_UPLOAD_EXTENSIONS)},
        )
    return resolved


def normalize_content_type(content_type: str | None) -> str | None:
    """Return a bare lowercase media type without parameters."""
    if content_type is None:
        return None
    bare = content_type.split(";", 1)[0].strip().lower()
    return bare or None


def detect_format_from_magic(head: bytes) -> FileFormat | None:
    """Return the format indicated by the leading bytes, when they identify one."""
    if any(head.startswith(prefix) for prefix in ZIP_MAGIC_PREFIXES):
        return FileFormat.XLSX
    if head.startswith(PARQUET_MAGIC):
        return FileFormat.PARQUET
    return None


def looks_like_text(head: bytes) -> bool:
    """Return whether the leading bytes can reasonably be read as delimited text.

    A NUL byte, or a payload dominated by control characters, marks a binary
    file. The check is deliberately conservative: it rejects what is certainly
    not text and leaves the encoding decision to the sniffer.
    """
    if not head:
        return False
    if b"\x00" in head:
        return False
    control_count = sum(1 for value in head if value in _CONTROL_BYTES)
    if control_count / len(head) > _MAX_CONTROL_FRACTION:
        return False
    return any(value not in _CONTROL_BYTES and not chr(value).isspace() for value in head)


def inspect_file_type(
    *,
    filename: str,
    content_type: str | None,
    head: bytes,
) -> FileTypeVerdict:
    """Validate an upload's name, extension, declared type, and leading bytes."""
    extension = normalized_extension(filename)
    detected = format_for_extension(extension)
    magic_format = detect_format_from_magic(head)
    warnings: list[str] = []

    if detected in _TEXT_FORMATS:
        if magic_format is not None:
            raise ValidationError(
                f"The file is named '{extension}' but its content is a "
                f"{magic_format.value} container.",
                details={"filename": filename, "detected_format": magic_format.value},
            )
        if not looks_like_text(head):
            raise ValidationError(
                f"The file is named '{extension}' but its content is not text.",
                details={"filename": filename},
            )
    elif detected is FileFormat.XLSX:
        if magic_format is not FileFormat.XLSX:
            raise ValidationError(
                "The file is named '.xlsx' but it is not a ZIP container, so it "
                "cannot be a workbook.",
                details={"filename": filename},
            )
    elif detected is FileFormat.PARQUET:
        if magic_format is not FileFormat.PARQUET:
            raise ValidationError(
                "The file is named '.parquet' but it does not start with the Parquet signature.",
                details={"filename": filename},
            )

    normalized_type = normalize_content_type(content_type)
    accepted: bool | None = None
    if normalized_type is not None:
        accepted = normalized_type in SUPPORTED_MIME_TYPES.get(extension, frozenset())
        if not accepted:
            warnings.append(
                f"The declared content type '{normalized_type}' is not one of the "
                f"accepted types for '{extension}'; the extension and the file "
                "content were used instead."
            )

    return FileTypeVerdict(
        filename=filename,
        extension=extension,
        format=detected,
        magic_format=magic_format,
        content_type=normalized_type,
        content_type_accepted=accepted,
        warnings=tuple(warnings),
    )
