"""Network chunk planning, range validation, and streaming part assembly.

A chunked upload is a sequence of byte ranges with individual digests. This
module plans the parts of a declared file size, validates an incoming part
against its declared range, and assembles stored parts into one object while
verifying each part digest and the digest of the whole upload.

Nothing here touches the database: the planner and the assembler are pure
functions over a declared size and an object store, so the same code serves the
API process, the worker, and the tests.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import BinaryIO, Final

from trendsmapp.errors import ConflictError, ValidationError
from trendsmapp.hashing import DEFAULT_CHUNK_SIZE, hashes_match, is_sha256_hex
from trendsmapp.storage.base import ObjectStore

__all__ = [
    "MAX_PART_COUNT",
    "AssemblyResult",
    "PartPlan",
    "StoredPartRef",
    "TextBatch",
    "assemble_parts",
    "count_rows",
    "expected_part_size",
    "parse_content_range",
    "part_count",
    "plan_parts",
    "validate_part_request",
]

_CONTENT_RANGE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^bytes\s*=?\s*(?P<start>\d+)\s*-\s*(?P<end>\d+)(?:[/\s]\s*(?:\d+|\*))?$"
)

#: The largest number of parts a single upload session may declare.
MAX_PART_COUNT: Final[int] = 100_000


@dataclass(frozen=True, slots=True)
class PartPlan:
    """The declared byte range of one part of an upload."""

    part_number: int
    start_byte: int
    end_byte: int
    size_bytes: int


@dataclass(frozen=True, slots=True)
class StoredPartRef:
    """A stored part as recorded in the upload session."""

    key: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class TextBatch:
    """One deterministic batch of table rows, read as exact text.

    Every reader in the ingestion layer produces these batches. ``rows`` holds
    the source text of each cell unchanged, and ``missing`` marks the cells for
    which the source recorded no value at all. Keeping the two apart is what
    lets normalization distinguish a missing observation from an unparsable
    one, and it is why a reader never coerces a value into a number.
    """

    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    missing: tuple[tuple[bool, ...], ...]
    first_row_index: int

    def __post_init__(self) -> None:
        width = len(self.columns)
        if not self.columns:
            raise ValidationError("A batch requires at least one column.")
        if len(self.rows) != len(self.missing):
            raise ValidationError(
                "A batch must record missingness for every row.",
                details={"rows": len(self.rows), "missing_rows": len(self.missing)},
            )
        for index, row in enumerate(self.rows):
            if len(row) != width:
                raise ValidationError(
                    "Every batch row must have one cell per column.",
                    details={"row": index, "cells": len(row), "columns": width},
                )
            if len(self.missing[index]) != width:
                raise ValidationError(
                    "Every batch row must record missingness for each column.",
                    details={"row": index, "missing_cells": len(self.missing[index])},
                )

    @property
    def row_count(self) -> int:
        """Return the number of data rows in the batch."""
        return len(self.rows)

    @property
    def missing_cell_count(self) -> int:
        """Return the number of cells the source recorded as absent."""
        return sum(1 for row in self.missing for flag in row if flag)


def count_rows(batches: Iterable[TextBatch]) -> int:
    """Return the number of rows across an iterable of batches."""
    return sum(batch.row_count for batch in batches)


@dataclass(frozen=True, slots=True)
class AssemblyResult:
    """The outcome of assembling the parts of an upload."""

    sha256: str
    size_bytes: int
    part_count: int


def part_count(total_bytes: int, chunk_size: int) -> int:
    """Return the number of parts a file of ``total_bytes`` is divided into."""
    if total_bytes < 1:
        raise ValidationError(
            "An upload must declare at least one byte.",
            details={"total_bytes": total_bytes},
        )
    if chunk_size < 1:
        raise ValidationError("A chunk size must be positive.", details={"chunk": chunk_size})
    return (total_bytes + chunk_size - 1) // chunk_size


def plan_parts(total_bytes: int, chunk_size: int) -> tuple[PartPlan, ...]:
    """Return the declared byte range of every part of an upload.

    Part numbering starts at one, which matches the HTTP part number. Every
    part except the last carries exactly ``chunk_size`` bytes.
    """
    count = part_count(total_bytes, chunk_size)
    if count > MAX_PART_COUNT:
        raise ValidationError(
            "The upload would require more parts than the protocol supports.",
            details={"parts": count, "maximum_parts": MAX_PART_COUNT},
        )
    plans: list[PartPlan] = []
    for part_number in range(1, count + 1):
        start = (part_number - 1) * chunk_size
        end = min(start + chunk_size, total_bytes) - 1
        plans.append(
            PartPlan(
                part_number=part_number,
                start_byte=start,
                end_byte=end,
                size_bytes=end - start + 1,
            )
        )
    return tuple(plans)


def expected_part_size(*, total_bytes: int, chunk_size: int, part_number: int) -> int:
    """Return the declared size of one part."""
    plans = plan_parts(total_bytes, chunk_size)
    if part_number < 1 or part_number > len(plans):
        raise ValidationError(
            "The part number is outside the declared upload.",
            details={"part_number": part_number, "part_count": len(plans)},
        )
    return plans[part_number - 1].size_bytes


def parse_content_range(value: str) -> tuple[int, int]:
    """Parse a ``Content-Range`` value into an inclusive byte range.

    Both the HTTP header form ``bytes 0-1023/2048`` (with an optional total) and
    the ``bytes=0-1023`` form are accepted; anything else is rejected.
    """
    if not isinstance(value, str):
        raise ValidationError("A content range is required for a part upload.")
    match = _CONTENT_RANGE_PATTERN.fullmatch(value.strip())
    if match is None:
        raise ValidationError(
            "The content range must have the form 'bytes start-end' (or 'bytes=start-end').",
            details={"content_range": value.strip()[:64]},
        )
    start = int(match.group("start"))
    end = int(match.group("end"))
    if end < start:
        raise ValidationError(
            "The content range ends before it starts.",
            details={"start": start, "end": end},
        )
    return start, end


def validate_part_request(
    *,
    part_number: int,
    content_range: str | None,
    total_bytes: int,
    chunk_size: int,
) -> PartPlan:
    """Validate an incoming part against its declared range.

    The range is optional: a client that uploads the declared parts in order
    may omit it, and the recorded byte count still has to match the plan.
    """
    plans = plan_parts(total_bytes, chunk_size)
    if part_number < 1 or part_number > len(plans):
        raise ValidationError(
            "The part number is outside the declared upload.",
            details={"part_number": part_number, "part_count": len(plans)},
        )
    plan = plans[part_number - 1]
    if content_range is not None:
        start, end = parse_content_range(content_range)
        if start != plan.start_byte or end != plan.end_byte:
            raise ValidationError(
                "The content range does not match the declared part.",
                details={
                    "part_number": part_number,
                    "expected_range": f"bytes={plan.start_byte}-{plan.end_byte}",
                    "received_range": f"bytes={start}-{end}",
                },
            )
    return plan


def assemble_parts(
    *,
    store: ObjectStore,
    parts: Sequence[StoredPartRef],
    destination: BinaryIO,
    expected_total_bytes: int,
    expected_sha256: str | None,
) -> AssemblyResult:
    """Stream stored parts into ``destination`` while verifying every digest.

    The destination is a temporary file the caller owns; this function never
    writes into the object store, because the assembled upload is stored by the
    caller under its content-addressed key once it is verified.
    """
    if not parts:
        raise ValidationError("An upload has no parts to assemble.")
    if expected_sha256 is not None and not is_sha256_hex(expected_sha256):
        raise ValidationError(
            "The declared upload digest is not a SHA-256 digest.",
            details={"sha256": expected_sha256[:128]},
        )
    total = hashlib.sha256()
    written = 0
    for part in parts:
        with store.open_stream(part.key) as handle:
            part_digest = hashlib.sha256()
            part_written = 0
            while True:
                chunk = handle.read(DEFAULT_CHUNK_SIZE)
                if not chunk:
                    break
                destination.write(chunk)
                total.update(chunk)
                part_digest.update(chunk)
                part_written += len(chunk)
                written += len(chunk)
                if written > expected_total_bytes:
                    raise ConflictError(
                        "The stored parts are larger than the declared upload size.",
                        details={"declared_bytes": expected_total_bytes, "bytes_read": written},
                    )
        if part_written != part.size_bytes:
            raise ConflictError(
                "A stored part does not match the size recorded for it.",
                details={
                    "key": part.key,
                    "recorded_bytes": part.size_bytes,
                    "stored_bytes": part_written,
                },
            )
        if part_digest.hexdigest() != part.sha256:
            raise ConflictError(
                "A stored part fails its digest check.",
                details={"key": part.key},
            )
    destination.flush()
    if written != expected_total_bytes:
        raise ConflictError(
            "The assembled upload does not match the declared size.",
            details={"declared_bytes": expected_total_bytes, "assembled_bytes": written},
        )
    digest = total.hexdigest()
    if expected_sha256 is not None and not hashes_match(expected_sha256, digest):
        raise ConflictError(
            "The assembled upload does not match the declared digest.",
            details={"declared_sha256": expected_sha256, "assembled_sha256": digest},
        )
    return AssemblyResult(sha256=digest, size_bytes=written, part_count=len(parts))
