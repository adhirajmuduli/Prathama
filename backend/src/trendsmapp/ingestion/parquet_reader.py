"""Parquet reader with explicit per-type text conversion.

Parquet files carry real types, and a reader that silently stringifies a
timestamp or a decimal would choose a convention the analyst never saw. Every
conversion rule is therefore written down and tested:

- booleans become ``true``/``false``;
- integers become decimal strings;
- floats become Python ``repr``, which is the shortest round-trip form, so
  ``nan``, ``inf``, and ``-inf`` survive as text and are flagged downstream as
  non-finite values instead of being hidden;
- decimals become their exact string form;
- strings pass through unchanged;
- binary columns are rejected, because decoding them is a decision the analyst
  must make before upload;
- timestamps become ISO 8601 text, keeping the offset when the column carries
  one, so the timestamp parser remains the single authority on time zones;
- nested, duration, interval, and union columns are rejected at selection time.

``missing`` marks the cells the source stored as null, which is distinct from
an empty string, and that distinction is what lets quality control separate a
missing observation from an unparsable one.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import BinaryIO, Final

import pyarrow as pa
import pyarrow.parquet as pq

from trendsmapp.constants import MAX_INGESTED_ROWS
from trendsmapp.errors import ParsingError, ResourceLimitError, ValidationError
from trendsmapp.ingestion.chunking import TextBatch
from trendsmapp.ingestion.security import require_seekable

__all__ = [
    "MAX_BATCH_ROWS",
    "ParquetColumnInfo",
    "ParquetInspection",
    "UnsupportedArrowTypeError",
    "arrow_value_to_text",
    "inspect_parquet",
    "read_parquet_batches",
]

#: Row groups are read in batches no larger than this.
MAX_BATCH_ROWS: Final[int] = 500_000


class UnsupportedArrowTypeError(Exception):
    """Raised when an Arrow value has no exact text representation."""

    def __init__(self, python_type: str) -> None:
        super().__init__(f"An Arrow value of type '{python_type}' has no text rule.")
        self.python_type = python_type


@dataclass(frozen=True, slots=True)
class ParquetColumnInfo:
    """One column of a Parquet file."""

    name: str
    arrow_type: str
    nullable: bool


@dataclass(frozen=True, slots=True)
class ParquetInspection:
    """The structural description of a Parquet file."""

    columns: tuple[ParquetColumnInfo, ...]
    row_count: int
    row_group_count: int
    created_by: str | None

    @property
    def column_names(self) -> tuple[str, ...]:
        """Return the column names in file order."""
        return tuple(column.name for column in self.columns)


def _rejection_reason(arrow_type: pa.DataType) -> str | None:
    """Return the rejection reason for a type that cannot become exact text."""
    if pa.types.is_nested(arrow_type):
        return "is nested and has no flat text form"
    if pa.types.is_union(arrow_type):
        return "is a union type"
    if pa.types.is_duration(arrow_type) or pa.types.is_interval(arrow_type):
        return "is a duration or interval"
    if pa.types.is_binary(arrow_type) or pa.types.is_large_binary(arrow_type):
        return "is binary, and decoding it is an analysis decision"
    if pa.types.is_dictionary(arrow_type):
        # The dictionary is decoded on read; the value type decides.
        return _rejection_reason(arrow_type.value_type)
    return None


def inspect_parquet(stream: BinaryIO) -> ParquetInspection:
    """Return the columns, row count, and writer metadata of a Parquet file."""
    require_seekable(stream, context="inspecting a Parquet file")
    stream.seek(0)
    parquet = _open_parquet(stream)
    schema = parquet.schema_arrow
    columns = tuple(
        ParquetColumnInfo(
            name=field.name,
            arrow_type=str(field.type),
            nullable=field.nullable,
        )
        for field in schema
    )
    return ParquetInspection(
        columns=columns,
        row_count=int(parquet.metadata.num_rows),
        row_group_count=int(parquet.metadata.num_row_groups),
        created_by=str(parquet.metadata.created_by),
    )


def read_parquet_batches(
    stream: BinaryIO,
    *,
    columns: Sequence[str],
    batch_rows: int,
    skip_leading_rows: int = 0,
) -> Iterator[TextBatch]:
    """Yield text batches of the selected columns of a Parquet file.

    The reader keeps the physical row order of the file. Row groups are read
    one at a time, so memory stays bounded by one row group, and the batches
    inside a group follow the requested size.
    """
    if not columns:
        raise ValidationError("A Parquet read requires at least one column.")
    if len(set(columns)) != len(columns):
        raise ValidationError("The selected columns must be unique.")
    if batch_rows < 1 or batch_rows > MAX_BATCH_ROWS:
        raise ValidationError(
            "The batch size is outside the accepted range.",
            details={"batch_rows": batch_rows, "maximum_batch_rows": MAX_BATCH_ROWS},
        )
    if skip_leading_rows < 0:
        raise ValidationError("The number of skipped rows cannot be negative.")

    require_seekable(stream, context="reading a Parquet file")
    stream.seek(0)
    parquet = _open_parquet(stream)
    schema = parquet.schema_arrow
    available = [field.name for field in schema]
    unknown = [name for name in columns if name not in available]
    if unknown:
        raise ValidationError(
            "The requested columns do not exist in the Parquet schema.",
            details={"unknown_columns": unknown, "available_columns": available},
        )
    for name in columns:
        arrow_type = schema.field(name).type
        reason = _rejection_reason(arrow_type)
        if reason is not None:
            raise ParsingError(
                f"Column '{name}' has type '{arrow_type}', which {reason}.",
                details={
                    "column": name,
                    "arrow_type": str(arrow_type),
                    "reason": "unsupported_column_type",
                },
            )

    total_rows = int(parquet.metadata.num_rows)
    if total_rows > MAX_INGESTED_ROWS:
        raise ResourceLimitError(
            "The Parquet file has more rows than this deployment ingests in one dataset.",
            details={"rows": total_rows, "maximum_rows": MAX_INGESTED_ROWS},
        )

    rows_to_skip = skip_leading_rows
    rows_emitted = 0
    names = list(columns)
    column_types = [schema.field(name).type for name in names]
    try:
        for batch in parquet.iter_batches(batch_size=batch_rows, columns=names):
            if rows_to_skip >= batch.num_rows:
                rows_to_skip -= batch.num_rows
                continue
            converted = _convert_batch(
                batch, names=names, column_types=column_types, rows_to_skip=rows_to_skip
            )
            rows_to_skip = 0
            if converted is None:
                continue
            rows, missing = converted
            yield TextBatch(
                columns=tuple(names),
                rows=rows,
                missing=missing,
                first_row_index=rows_emitted,
            )
            rows_emitted += len(rows)
    except pa.ArrowInvalid as exc:
        raise ParsingError(
            "The Parquet file could not be decoded.",
            details={"reason": "invalid_parquet_payload", "rows_read": rows_emitted},
        ) from exc


def _open_parquet(stream: BinaryIO) -> pq.ParquetFile:
    """Open a Parquet file, translating loader failures."""
    try:
        return pq.ParquetFile(stream)
    except (pa.ArrowInvalid, OSError, ValueError) as exc:
        raise ParsingError(
            "The file could not be read as a Parquet dataset.",
            details={"reason": "unreadable_parquet"},
        ) from exc


def _convert_batch(
    batch: pa.RecordBatch,
    *,
    names: list[str],
    column_types: list[pa.DataType],
    rows_to_skip: int,
) -> tuple[tuple[tuple[str, ...], ...], tuple[tuple[bool, ...], ...]] | None:
    """Convert one Arrow batch into rows of exact text with missing markers."""
    columns = [batch.column(index).to_pylist() for index in range(batch.num_columns)]
    rows: list[tuple[str, ...]] = []
    missing: list[tuple[bool, ...]] = []
    for row_index in range(rows_to_skip, batch.num_rows):
        row_text: list[str] = []
        row_missing: list[bool] = []
        for column_index, name in enumerate(names):
            value = columns[column_index][row_index]
            if value is None:
                row_text.append("")
                row_missing.append(True)
                continue
            try:
                row_text.append(arrow_value_to_text(value))
            except UnsupportedArrowTypeError as exc:
                raise ParsingError(
                    f"Column '{name}' holds a value of type '{exc.python_type}', "
                    "which has no text rule.",
                    details={"column": name, "reason": "unsupported_value_type"},
                ) from exc
            row_missing.append(False)
        rows.append(tuple(row_text))
        missing.append(tuple(row_missing))
    if not rows:
        return None
    return tuple(rows), tuple(missing)


def arrow_value_to_text(value: object) -> str:
    """Return the exact text form of an Arrow value.

    The rules are documented in the module docstring. A value type that has no
    rule raises :class:`UnsupportedArrowTypeError` with the Python type name,
    because a silent ``str()`` conversion would hide a scientific decision.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise UnsupportedArrowTypeError("bytes") from exc
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    raise UnsupportedArrowTypeError(type(value).__name__)
