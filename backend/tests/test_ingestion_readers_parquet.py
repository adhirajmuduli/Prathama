"""Tests for the Parquet reader and its per-type text conversion."""

from __future__ import annotations

import io
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import BinaryIO

import pytest

from trendsmapp.errors import ParsingError, ValidationError
from trendsmapp.ingestion.chunking import count_rows
from trendsmapp.ingestion.parquet_reader import (
    UnsupportedArrowTypeError,
    arrow_value_to_text,
    inspect_parquet,
    read_parquet_batches,
)


class NonSeekableStream:
    """A minimal non-seekable binary stream."""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self._position = 0

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            data = self._payload[self._position :]
            self._position = len(self._payload)
            return data
        data = self._payload[self._position : self._position + size]
        self._position += len(data)
        return data

    def readable(self) -> bool:
        return True


def _open(testdata_path: Path, name: str) -> BinaryIO:
    return io.BytesIO(testdata_path(name).read_bytes())


def test_inspect_parquet_describes_the_schema(testdata_path: Path) -> None:
    inspection = inspect_parquet(_open(testdata_path, "observations.parquet"))
    assert inspection.column_names == (
        "station",
        "value",
        "sampled_at",
        "collected_on",
        "sample_count",
        "is_valid",
        "salinity",
        "notes",
    )
    assert [column.arrow_type for column in inspection.columns] == [
        "string",
        "double",
        "timestamp[us, tz=UTC]",
        "date32[day]",
        "int32",
        "bool",
        "decimal128(10, 2)",
        "string",
    ]
    assert inspection.row_count == 3
    assert inspection.row_group_count == 1
    assert "parquet-cpp-arrow" in (inspection.created_by or "")


def test_reader_converts_every_typed_column_to_exact_text(testdata_path: Path) -> None:
    batches = list(
        read_parquet_batches(
            _open(testdata_path, "observations.parquet"),
            columns=(
                "station",
                "value",
                "sampled_at",
                "collected_on",
                "sample_count",
                "is_valid",
                "salinity",
                "notes",
            ),
            batch_rows=2,
        )
    )
    assert [batch.row_count for batch in batches] == [2, 1]
    rows = [row for batch in batches for row in batch.rows]
    assert rows[0] == (
        "St. A",
        "6.8",
        "2024-01-15T09:30:00+00:00",
        "2024-01-15",
        "3",
        "true",
        "12.40",
        "",
    )
    assert rows[1][1] == ""
    assert rows[1][7] == "missing value"
    assert rows[2][1] == "nan"

    missing = [flag for batch in batches for row in batch.missing for flag in row]
    assert missing.count(True) == 2


def test_reader_keeps_the_physical_row_order_and_indexes(testdata_path: Path) -> None:
    batches = list(
        read_parquet_batches(
            _open(testdata_path, "observations.parquet"),
            columns=("station",),
            batch_rows=1,
        )
    )
    assert [batch.row_count for batch in batches] == [1, 1, 1]
    assert [batch.first_row_index for batch in batches] == [0, 1, 2]
    assert [batch.rows[0][0] for batch in batches] == ["St. A", "St. B", "St. C"]


def test_reader_skips_leading_rows_on_request(testdata_path: Path) -> None:
    batches = list(
        read_parquet_batches(
            _open(testdata_path, "observations.parquet"),
            columns=("station", "sample_count"),
            batch_rows=2,
            skip_leading_rows=1,
        )
    )
    assert count_rows(batches) == 2
    assert batches[0].rows[0] == ("St. B", "2")


def test_reader_reads_a_selected_subset_of_columns(testdata_path: Path) -> None:
    batches = list(
        read_parquet_batches(
            _open(testdata_path, "observations.parquet"),
            columns=("station", "salinity"),
            batch_rows=10,
        )
    )
    assert batches[0].columns == ("station", "salinity")
    assert batches[0].rows[0] == ("St. A", "12.40")


def test_reader_rejects_unknown_columns(testdata_path: Path) -> None:
    with pytest.raises(ValidationError) as error:
        list(
            read_parquet_batches(
                _open(testdata_path, "observations.parquet"),
                columns=("station", "missing_column"),
                batch_rows=10,
            )
        )
    assert error.value.details["unknown_columns"] == ["missing_column"]
    assert "station" in error.value.details["available_columns"]


def test_reader_rejects_nested_columns(testdata_path: Path) -> None:
    with pytest.raises(ParsingError) as error:
        list(
            read_parquet_batches(
                _open(testdata_path, "nested_columns.parquet"),
                columns=("station", "replicates"),
                batch_rows=10,
            )
        )
    assert error.value.details["reason"] == "unsupported_column_type"
    assert error.value.details["column"] == "replicates"
    assert "nested" in str(error.value)


def test_reader_rejects_an_empty_column_selection(testdata_path: Path) -> None:
    with pytest.raises(ValidationError):
        list(
            read_parquet_batches(
                _open(testdata_path, "observations.parquet"), columns=(), batch_rows=10
            )
        )


def test_reader_rejects_duplicate_columns(testdata_path: Path) -> None:
    with pytest.raises(ValidationError):
        list(
            read_parquet_batches(
                _open(testdata_path, "observations.parquet"),
                columns=("station", "station"),
                batch_rows=10,
            )
        )


def test_reader_validates_the_batch_size(testdata_path: Path) -> None:
    with pytest.raises(ValidationError):
        list(
            read_parquet_batches(
                _open(testdata_path, "observations.parquet"),
                columns=("station",),
                batch_rows=0,
            )
        )
    with pytest.raises(ValidationError):
        list(
            read_parquet_batches(
                _open(testdata_path, "observations.parquet"),
                columns=("station",),
                batch_rows=1_000_000,
            )
        )


def test_reader_rejects_a_truncated_file(testdata_path: Path) -> None:
    with pytest.raises(ParsingError) as error:
        inspect_parquet(_open(testdata_path, "truncated.parquet"))
    assert error.value.details["reason"] == "unreadable_parquet"


def test_reader_requires_a_seekable_stream(testdata_path: Path) -> None:
    with pytest.raises(ValidationError):
        list(
            read_parquet_batches(
                NonSeekableStream(testdata_path("observations.parquet").read_bytes()),
                columns=("station",),
                batch_rows=10,
            )
        )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ""),
        (True, "true"),
        (False, "false"),
        (12, "12"),
        (-3, "-3"),
        (6.8, "6.8"),
        (float("nan"), "nan"),
        (float("inf"), "inf"),
        (float("-inf"), "-inf"),
        (Decimal("12.40"), "12.40"),
        ("plain", "plain"),
        (date(2024, 2, 12), "2024-02-12"),
        (datetime(2024, 2, 12, 10, 5, tzinfo=UTC), "2024-02-12T10:05:00+00:00"),
        (time(9, 30), "09:30:00"),
    ],
)
def test_arrow_value_to_text_follows_the_documented_rules(value: object, expected: str) -> None:
    assert arrow_value_to_text(value) == expected


def test_arrow_value_to_text_rejects_untyped_values() -> None:
    with pytest.raises(UnsupportedArrowTypeError) as error:
        arrow_value_to_text(object())
    assert "object" in str(error.value)
