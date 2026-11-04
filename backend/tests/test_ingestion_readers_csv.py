"""Tests for the PyArrow-based delimited reader."""

from __future__ import annotations

import io
from pathlib import Path
from typing import BinaryIO

import pytest

from trendsmapp.domain.enums import FileFormat
from trendsmapp.errors import ParsingError, ValidationError
from trendsmapp.ingestion.chunking import count_rows
from trendsmapp.ingestion.csv_reader import CsvReadOptions, count_csv_rows, read_csv_batches
from trendsmapp.ingestion.sniffing import sniff_delimited_bytes

LONG_FIELDS = (
    "station",
    "latitude",
    "longitude",
    "sampled_at",
    "parameter",
    "value",
    "unit",
    "qualifier",
    "depth_m",
    "notes",
)

FIRST_DATA_ROW = (
    "St. A",
    "19.7350",
    "85.4700",
    "2024-01-15T09:30:00Z",
    "dissolved_oxygen",
    "6.8",
    "mg/L",
    "",
    "0.5",
    "",
)


def _open_csv(testdata_path: Path, name: str) -> BinaryIO:
    return io.BytesIO(testdata_path(name).read_bytes())


def _long_options(encoding: str = "utf-8") -> CsvReadOptions:
    return CsvReadOptions(
        column_names=LONG_FIELDS,
        delimiter=",",
        encoding=encoding,
        skip_leading_rows=1,
    )


def test_reader_preserves_every_raw_value_as_text(testdata_path: Path) -> None:
    batches = list(
        read_csv_batches(_open_csv(testdata_path, "long_observations.csv"), _long_options())
    )
    assert len(batches) == 1
    batch = batches[0]
    assert batch.row_count == 12
    assert batch.columns == LONG_FIELDS
    assert batch.first_row_index == 0
    assert batch.rows[0] == FIRST_DATA_ROW
    assert batch.rows[2][5] == "<0.01"
    assert batch.rows[11][5] == "nan"
    assert batch.rows[4][5] == "25.0"


def test_reader_marks_absent_cells_as_missing(testdata_path: Path) -> None:
    batches = list(
        read_csv_batches(_open_csv(testdata_path, "long_observations.csv"), _long_options())
    )
    batch = batches[0]
    first_row = batch.rows[0]
    missing_flags = batch.missing[0]
    for index, cell in enumerate(first_row):
        assert missing_flags[index] is (cell == "")
    qualifier_index = LONG_FIELDS.index("qualifier")
    assert missing_flags[qualifier_index] is True
    value_index = LONG_FIELDS.index("value")
    assert missing_flags[value_index] is False


def test_reader_keeps_the_physical_row_order(testdata_path: Path) -> None:
    batches = list(
        read_csv_batches(_open_csv(testdata_path, "long_observations.csv"), _long_options())
    )
    batch = batches[0]
    stations = [row[0] for row in batch.rows]
    assert stations == ["St. A", "St. A", "St. B", "St. B"] * 3


def test_reader_skips_leading_rows_on_request(testdata_path: Path) -> None:
    batches = list(
        read_csv_batches(_open_csv(testdata_path, "long_observations.csv"), _long_options())
    )
    assert batches[0].rows[0] == FIRST_DATA_ROW
    assert batches[0].first_row_index == 0

    including_header = list(
        read_csv_batches(
            _open_csv(testdata_path, "long_observations.csv"),
            CsvReadOptions(column_names=LONG_FIELDS, delimiter=","),
        )
    )
    header_batch = including_header[0]
    assert header_batch.rows[0][:2] == ("station", "latitude")


def test_reader_reads_tab_delimited_files(testdata_path: Path) -> None:
    options = CsvReadOptions(
        column_names=("station", "sampled_at", "parameter", "value", "unit"),
        delimiter="\t",
        skip_leading_rows=1,
    )
    batches = list(read_csv_batches(_open_csv(testdata_path, "observations.tsv"), options))
    assert count_rows(batches) == 4
    assert batches[0].rows[1] == ("St. B", "2024-01-15T10:05:00Z", "salinity", "12.4", "psu")


def test_reader_transcodes_non_utf8_files(testdata_path: Path) -> None:
    options = CsvReadOptions(
        column_names=("station", "sampled_at", "parameter", "value", "unit"),
        delimiter=",",
        encoding="cp1252",
    )
    batches = list(read_csv_batches(_open_csv(testdata_path, "cp1252_non_utf8.csv"), options))
    assert batches[0].rows[0] == ("station", "sampled_at", "parameter", "value", "unit")
    assert batches[0].rows[1] == ("St. A", "2024-01-15T09:30:00Z", "temperature", "21.4", "°C")
    assert batches[0].rows[2] == ("St. B", "2024-01-15T10:05:00Z", "phosphat", "0.03", "µg/l")


def test_reader_reports_inconsistent_field_counts_without_leaking_content(
    testdata_path: Path,
) -> None:
    options = CsvReadOptions(
        column_names=("station", "latitude", "longitude", "sampled_at", "parameter", "value"),
        delimiter=",",
    )
    with pytest.raises(ParsingError) as error:
        list(read_csv_batches(_open_csv(testdata_path, "malformed_ragged.csv"), options))
    message = str(error.value)
    assert "7 fields" in message
    assert "6" in message
    assert "extra_field" not in message
    assert error.value.details["reason"] == "inconsistent_field_count"
    assert error.value.details["expected_columns"] == 6
    assert error.value.details["found_columns"] == 7


def test_reader_reports_unterminated_quotes(testdata_path: Path) -> None:
    options = CsvReadOptions(column_names=("station", "notes", "parameter", "value"), delimiter=",")
    with pytest.raises(ParsingError) as error:
        list(read_csv_batches(_open_csv(testdata_path, "malformed_unclosed_quote.csv"), options))
    assert error.value.code == "parsing_error"
    assert "unterminated note" not in str(error.value)


def test_reader_rejects_an_empty_table(testdata_path: Path) -> None:
    options = CsvReadOptions(column_names=("station", "value"), delimiter=",")
    with pytest.raises(ParsingError) as error:
        list(read_csv_batches(_open_csv(testdata_path, "empty.csv"), options))
    assert "no records" in str(error.value)
    assert error.value.details["reason"] == "empty_table"


def test_count_csv_rows_counts_data_rows(testdata_path: Path) -> None:
    assert count_csv_rows(_open_csv(testdata_path, "long_observations.csv"), _long_options()) == 12
    assert (
        count_csv_rows(
            _open_csv(testdata_path, "cp1252_non_utf8.csv"),
            CsvReadOptions(
                column_names=("station", "sampled_at", "parameter", "value", "unit"),
                delimiter=",",
                encoding="cp1252",
            ),
        )
        == 3
    )


def test_reader_options_are_validated() -> None:
    with pytest.raises(ValidationError):
        CsvReadOptions(column_names=(), delimiter=",")
    with pytest.raises(ValidationError):
        CsvReadOptions(column_names=("a", "a"), delimiter=",")
    with pytest.raises(ValidationError):
        CsvReadOptions(column_names=("a", ""), delimiter=",")
    with pytest.raises(ValidationError):
        CsvReadOptions(column_names=("a",), delimiter=";;")
    with pytest.raises(ValidationError):
        CsvReadOptions(column_names=("a",), delimiter=",", quote_char='""')
    with pytest.raises(ValidationError):
        CsvReadOptions(column_names=("a",), delimiter=",", skip_leading_rows=-1)
    with pytest.raises(ValidationError):
        CsvReadOptions(column_names=("a",), delimiter=",", batch_rows=0)
    with pytest.raises(ValidationError):
        CsvReadOptions(column_names=("a",), delimiter=",", block_bytes=1024)
    with pytest.raises(ValidationError):
        CsvReadOptions(column_names=("a",), delimiter=",", block_bytes=128 * 1024 * 1024)


def test_reader_streams_batches_at_the_requested_size(testdata_path: Path) -> None:
    options = CsvReadOptions(
        column_names=LONG_FIELDS, delimiter=",", skip_leading_rows=1, batch_rows=5
    )
    batches = list(read_csv_batches(_open_csv(testdata_path, "long_observations.csv"), options))
    assert [batch.row_count for batch in batches] == [5, 5, 2]
    assert [batch.first_row_index for batch in batches] == [0, 5, 10]
    assert count_rows(batches) == 12


def test_reader_and_sniffer_agree_on_the_field_names(testdata_path: Path) -> None:
    sniffed = sniff_delimited_bytes(
        testdata_path("long_observations.csv").read_bytes(), file_format=FileFormat.CSV
    )
    assert sniffed.fields == LONG_FIELDS
    assert sniffed.delimiter is not None
    options = CsvReadOptions(
        column_names=sniffed.fields, delimiter=sniffed.delimiter, skip_leading_rows=1
    )
    batches = list(read_csv_batches(_open_csv(testdata_path, "long_observations.csv"), options))
    assert count_rows(batches) == 12
