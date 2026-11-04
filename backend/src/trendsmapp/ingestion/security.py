"""Upload defenses: size, archive, workbook, and resource-exhaustion limits.

Every untrusted input passes through this module before a parser sees it. The
limits are hard ceilings from :mod:`trendsmapp.constants`; a payload above a
ceiling is rejected with a structured error, never truncated, because a
truncated table would silently change the scientific content of a dataset.

The archive inspection is the only place that opens the ZIP container inside an
``.xlsx`` file. It runs before OpenPyXL so that a decompression bomb, a
macro-enabled workbook renamed to ``.xlsx``, or an archive member with a
traversal path is rejected without being expanded.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from typing import BinaryIO, Final

from trendsmapp.constants import (
    MAX_DECOMPRESSION_RATIO,
    MAX_INGESTED_COLUMNS,
    MAX_INGESTED_ROWS,
    MAX_WORKBOOK_CELLS,
    MAX_WORKBOOK_SHEETS,
    MAX_WORKBOOK_UNCOMPRESSED_BYTES,
    MAX_ZIP_MEMBERS,
    MIN_COMPRESSION_RATIO_CHECK_BYTES,
)
from trendsmapp.errors import ResourceLimitError, ValidationError

__all__ = [
    "ZipInspection",
    "enforce_cell_ceiling",
    "enforce_column_ceiling",
    "enforce_row_ceiling",
    "enforce_upload_size",
    "enforce_workbook_sheet_ceiling",
    "enforce_zip_limits",
    "inspect_zip_container",
    "require_seekable",
    "unsafe_member_name",
]

#: Members that turn a workbook into an executable document.
_MACRO_MEMBER_PATTERN: Final[str] = "vbaproject.bin"

#: Archive members that never occur inside a well-formed workbook. Their
#: presence means the container carries something a workbook cannot contain.
_NESTED_ARCHIVE_SUFFIXES: Final[tuple[str, ...]] = (
    ".zip",
    ".xlsx",
    ".xlsm",
    ".xlsb",
    ".jar",
    ".tar",
    ".gz",
    ".bz2",
    ".7z",
    ".rar",
    ".exe",
    ".dll",
    ".scr",
    ".js",
    ".vbs",
)


@dataclass(frozen=True, slots=True)
class ZipInspection:
    """The result of inspecting the ZIP container of a workbook."""

    member_count: int
    total_uncompressed_bytes: int
    largest_member_bytes: int
    max_member_ratio: float
    macro_members: tuple[str, ...]
    unsafe_member_names: tuple[str, ...]
    nested_archive_members: tuple[str, ...]
    ratio_violation_members: tuple[str, ...]

    @property
    def is_safe(self) -> bool:
        """Return whether the container passed every structural check."""
        return not (
            self.macro_members
            or self.unsafe_member_names
            or self.nested_archive_members
            or self.ratio_violation_members
        )


def require_seekable(stream: BinaryIO, *, context: str) -> None:
    """Raise when a reader receives a stream it cannot rewind."""
    seekable = getattr(stream, "seekable", None)
    if not callable(seekable) or not seekable():
        raise ValidationError(
            f"{context} requires a seekable stream; the caller must provide a "
            "rewindable copy of the stored object.",
            details={"context": context},
        )


def enforce_upload_size(size_bytes: int, *, maximum_bytes: int) -> None:
    """Reject an upload whose declared or actual size exceeds the ceiling."""
    if size_bytes < 0:
        raise ValidationError("An upload size cannot be negative.", details={"size": size_bytes})
    if size_bytes > maximum_bytes:
        raise ResourceLimitError(
            "The upload exceeds the maximum accepted file size.",
            details={"size_bytes": size_bytes, "maximum_bytes": maximum_bytes},
        )


def enforce_row_ceiling(rows_seen: int) -> None:
    """Reject a table with more rows than the ingestion ceiling."""
    if rows_seen > MAX_INGESTED_ROWS:
        raise ResourceLimitError(
            "The table has more rows than this deployment ingests in one dataset.",
            details={"rows": rows_seen, "maximum_rows": MAX_INGESTED_ROWS},
        )


def enforce_column_ceiling(columns_seen: int) -> None:
    """Reject a table with more columns than the ingestion ceiling."""
    if columns_seen > MAX_INGESTED_COLUMNS:
        raise ResourceLimitError(
            "The table has more columns than this deployment ingests in one dataset.",
            details={"columns": columns_seen, "maximum_columns": MAX_INGESTED_COLUMNS},
        )


def enforce_workbook_sheet_ceiling(sheet_count: int) -> None:
    """Reject a workbook with more sheets than the ceiling."""
    if sheet_count > MAX_WORKBOOK_SHEETS:
        raise ResourceLimitError(
            "The workbook has more sheets than this deployment accepts.",
            details={"sheets": sheet_count, "maximum_sheets": MAX_WORKBOOK_SHEETS},
        )


def enforce_cell_ceiling(cells_seen: int) -> None:
    """Reject a workbook sheet with more cells than the ceiling."""
    if cells_seen > MAX_WORKBOOK_CELLS:
        raise ResourceLimitError(
            "The worksheet has more cells than this deployment accepts.",
            details={"cells": cells_seen, "maximum_cells": MAX_WORKBOOK_CELLS},
        )


def inspect_zip_container(stream: BinaryIO) -> ZipInspection:
    """Inspect the ZIP container of a workbook without expanding its members.

    The stream is rewound to the beginning before the function returns so that
    the caller can hand it to the workbook reader.
    """
    require_seekable(stream, context="inspecting a workbook container")
    stream.seek(0)
    try:
        with zipfile.ZipFile(stream) as archive:
            members = archive.infolist()
            total_uncompressed = 0
            largest = 0
            max_ratio = 0.0
            macro_members: list[str] = []
            unsafe_names: list[str] = []
            nested: list[str] = []
            ratio_violations: list[str] = []
            for member in members:
                total_uncompressed += member.file_size
                largest = max(largest, member.file_size)
                lowered = member.filename.lower()
                if lowered.endswith(_MACRO_MEMBER_PATTERN) or "/macrosheets/" in lowered:
                    macro_members.append(member.filename)
                if unsafe_member_name(member.filename):
                    unsafe_names.append(member.filename)
                if lowered.endswith(_NESTED_ARCHIVE_SUFFIXES):
                    nested.append(member.filename)
                if (
                    member.file_size >= MIN_COMPRESSION_RATIO_CHECK_BYTES
                    and member.compress_size > 0
                ):
                    ratio = member.file_size / member.compress_size
                    max_ratio = max(max_ratio, ratio)
                    if ratio > MAX_DECOMPRESSION_RATIO:
                        ratio_violations.append(member.filename)
            inspection = ZipInspection(
                member_count=len(members),
                total_uncompressed_bytes=total_uncompressed,
                largest_member_bytes=largest,
                max_member_ratio=max_ratio,
                macro_members=tuple(macro_members),
                unsafe_member_names=tuple(unsafe_names),
                nested_archive_members=tuple(nested),
                ratio_violation_members=tuple(ratio_violations),
            )
    except zipfile.BadZipFile as exc:
        raise ValidationError(
            "The workbook container is not a readable ZIP archive.",
            details={"reason": "bad_zip_container"},
        ) from exc
    finally:
        stream.seek(0)
    return inspection


def enforce_zip_limits(inspection: ZipInspection, *, label: str) -> None:
    """Reject a ZIP container that violates a structural defense."""
    if inspection.member_count > MAX_ZIP_MEMBERS:
        raise ResourceLimitError(
            f"The {label} contains more archive members than this deployment accepts.",
            details={"members": inspection.member_count, "maximum_members": MAX_ZIP_MEMBERS},
        )
    if inspection.total_uncompressed_bytes > MAX_WORKBOOK_UNCOMPRESSED_BYTES:
        raise ResourceLimitError(
            f"The {label} expands to more bytes than this deployment accepts.",
            details={
                "uncompressed_bytes": inspection.total_uncompressed_bytes,
                "maximum_bytes": MAX_WORKBOOK_UNCOMPRESSED_BYTES,
            },
        )
    if inspection.macro_members:
        raise ValidationError(
            "Macro-enabled workbooks are not accepted.",
            details={"members": list(inspection.macro_members)},
        )
    if inspection.unsafe_member_names:
        raise ValidationError(
            f"The {label} contains archive members with unsafe paths.",
            details={"members": list(inspection.unsafe_member_names)},
        )
    if inspection.nested_archive_members:
        raise ValidationError(
            f"The {label} contains nested archives, which a workbook never contains.",
            details={"members": list(inspection.nested_archive_members)},
        )
    if inspection.ratio_violation_members:
        raise ResourceLimitError(
            f"The {label} contains archive members whose compression ratio exceeds "
            "the accepted limit.",
            details={
                "members": list(inspection.ratio_violation_members),
                "maximum_ratio": MAX_DECOMPRESSION_RATIO,
            },
        )


def unsafe_member_name(name: str) -> bool:
    """Return whether an archive member name could escape an extraction root.

    On Windows, Python's ``zipfile`` rewrites backslashes to slashes when a
    member is read, so a hostile archive built on another system is still worth
    screening: a Linux reader sees the raw name this function classifies.
    """
    if not name:
        return True
    if name.startswith(("/", "\\")):
        return True
    if "\\" in name:
        return True
    if ":" in name:
        return True
    return any(segment in {"..", "."} for segment in name.split("/"))
