"""Tests for the read-only workbook reader and its cell policies."""

from __future__ import annotations

import io
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from trendsmapp.errors import ParsingError, ValidationError
from trendsmapp.ingestion.chunking import count_rows
from trendsmapp.ingestion.excel_reader import (
    ExcelReadOptions,
    ExcelSheetReader,
    UnsupportedCellValueError,
    excel_cell_to_text,
    inspect_workbook,
    read_excel_sheet_names,
)

COLUMN_NAMES = (
    "station",
    "sampled_at",
    "value",
    "valid_flag",
    "collected_on",
    "computed_total",
)
MAPPED_WITHOUT_FORMULAS = (
    "station",
    "sampled_at",
    "value",
    "valid_flag",
    "collected_on",
)


def test_inspect_workbook_describes_the_sheets(testdata_path: Path) -> None:
    inspection = inspect_workbook(io.BytesIO(testdata_path("observations.xlsx").read_bytes()))
    assert [
        (sheet.title, sheet.declared_rows, sheet.declared_columns) for sheet in inspection.sheets
    ] == [
        ("Observations", 4, 6),
        ("Notes", 1, 1),
    ]
    assert inspection.sheet_count == 2
    assert inspection.declared_cells == 4 * 6 + 1 * 1
    assert inspection.container.is_safe


def test_read_excel_sheet_names_preserves_workbook_order(testdata_path: Path) -> None:
    names = read_excel_sheet_names(io.BytesIO(testdata_path("observations.xlsx").read_bytes()))
    assert names == ("Observations", "Notes")


def test_reader_emits_every_cell_as_exact_text(testdata_path: Path) -> None:
    reader = ExcelSheetReader(
        io.BytesIO(testdata_path("observations.xlsx").read_bytes()),
        ExcelReadOptions(column_names=COLUMN_NAMES, mapped_columns=MAPPED_WITHOUT_FORMULAS),
    )
    batches = list(reader)
    assert count_rows(batches) == 4
    rows = [row for batch in batches for row in batch.rows]
    assert rows[0] == (
        "station",
        "sampled_at",
        "value",
        "valid_flag",
        "collected_on",
        "computed_total",
    )
    assert rows[1] == (
        "St. A",
        "2024-01-15T09:30:00Z",
        "6.8",
        "true",
        "2024-01-15T09:30:00",
        "",
    )
    assert rows[2] == ("St. B", "2024-02-12T10:05:00Z", "12", "false", "2024-02-12T00:00:00", "")
    assert rows[3] == ("St. C", "2024-03-10T09:45:00Z", "", "true", "", "")


def test_reader_marks_absent_cells_and_reports_formula_cells(testdata_path: Path) -> None:
    reader = ExcelSheetReader(
        io.BytesIO(testdata_path("observations.xlsx").read_bytes()),
        ExcelReadOptions(column_names=COLUMN_NAMES, mapped_columns=MAPPED_WITHOUT_FORMULAS),
    )
    batches = list(reader)
    header_missing = batches[0].missing[0]
    assert header_missing == (False,) * 6
    formula_row_missing = batches[0].missing[1]
    assert formula_row_missing[5] is True
    assert formula_row_missing[:5] == (False, False, False, False, False)

    issues = reader.issues
    assert [(issue.kind, issue.row, issue.column_name) for issue in issues] == [
        ("formula", 2, "computed_total"),
        ("formula", 3, "computed_total"),
    ]


def test_reader_skips_leading_rows_on_request(testdata_path: Path) -> None:
    reader = ExcelSheetReader(
        io.BytesIO(testdata_path("observations.xlsx").read_bytes()),
        ExcelReadOptions(
            column_names=COLUMN_NAMES,
            mapped_columns=MAPPED_WITHOUT_FORMULAS,
            skip_leading_rows=1,
        ),
    )
    batches = list(reader)
    assert count_rows(batches) == 3
    assert batches[0].rows[0][0] == "St. A"
    assert batches[0].first_row_index == 0


def test_reader_rejects_a_formula_in_a_mapped_column(testdata_path: Path) -> None:
    reader = ExcelSheetReader(
        io.BytesIO(testdata_path("observations.xlsx").read_bytes()),
        ExcelReadOptions(column_names=COLUMN_NAMES),
    )
    with pytest.raises(ParsingError) as error:
        list(reader)
    message = str(error.value)
    assert "formula" in message
    assert "computed_total" in message
    assert error.value.details["reason"] == "formula_cell"
    assert error.value.details["row"] == 2


def test_reader_uses_cached_formula_values_only_when_accepted(testdata_path: Path) -> None:
    reader = ExcelSheetReader(
        io.BytesIO(testdata_path("formulas_cached.xlsx").read_bytes()),
        ExcelReadOptions(
            column_names=COLUMN_NAMES,
            mapped_columns=MAPPED_WITHOUT_FORMULAS,
            accept_cached_formula_values=True,
        ),
    )
    batches = list(reader)
    rows = [row for batch in batches for row in batch.rows]
    assert rows[1][5] == "18.8"
    assert rows[2][5] == ""
    assert [
        (issue.kind, issue.row, issue.column_name, issue.detail) for issue in reader.issues
    ] == [
        ("formula", 2, "computed_total", "the cached value of the formula was used"),
        (
            "formula_without_cached_value",
            3,
            "computed_total",
            "the formula has no cached value in the file",
        ),
    ]


def test_reader_rejects_a_formula_without_a_cached_value_in_a_mapped_column(
    testdata_path: Path,
) -> None:
    reader = ExcelSheetReader(
        io.BytesIO(testdata_path("formulas_cached.xlsx").read_bytes()),
        ExcelReadOptions(column_names=COLUMN_NAMES, accept_cached_formula_values=True),
    )
    with pytest.raises(ParsingError) as error:
        list(reader)
    assert error.value.details["reason"] == "formula_without_cached_value"
    assert error.value.details["row"] == 3


def test_reader_rejects_error_cells_in_mapped_columns(testdata_path: Path) -> None:
    reader = ExcelSheetReader(
        io.BytesIO(testdata_path("error_cells.xlsx").read_bytes()),
        ExcelReadOptions(column_names=COLUMN_NAMES),
    )
    with pytest.raises(ParsingError) as error:
        list(reader)
    assert error.value.details["reason"] == "error_cell"
    assert error.value.details["error_code"] == "#DIV/0!"
    assert error.value.details["row"] == 2


def test_reader_reports_error_cells_in_unmapped_columns(testdata_path: Path) -> None:
    reader = ExcelSheetReader(
        io.BytesIO(testdata_path("error_cells.xlsx").read_bytes()),
        ExcelReadOptions(column_names=COLUMN_NAMES, mapped_columns=("station", "sampled_at")),
    )
    batches = list(reader)
    rows = [row for batch in batches for row in batch.rows]
    assert rows[1][2] == ""
    error_issues = [issue for issue in reader.issues if issue.kind == "error_cell"]
    assert [(issue.row, issue.column_name, issue.detail) for issue in error_issues] == [
        (2, "value", "#DIV/0!")
    ]


def test_reader_rejects_a_row_wider_than_the_declared_columns(
    testdata_path: Path,
) -> None:
    reader = ExcelSheetReader(
        io.BytesIO(testdata_path("observations.xlsx").read_bytes()),
        ExcelReadOptions(column_names=("station", "sampled_at")),
    )
    with pytest.raises(ParsingError) as error:
        list(reader)
    assert error.value.details["cells"] == 6
    assert error.value.details["columns"] == 2


def test_reader_pads_rows_shorter_than_the_declared_columns(
    testdata_path: Path,
) -> None:
    reader = ExcelSheetReader(
        io.BytesIO(testdata_path("observations.xlsx").read_bytes()),
        ExcelReadOptions(
            column_names=(*COLUMN_NAMES, "extra_column"),
            mapped_columns=MAPPED_WITHOUT_FORMULAS,
        ),
    )
    batches = list(reader)
    rows = [row for batch in batches for row in batch.rows]
    for row in rows:
        assert len(row) == 7
        assert row[6] == ""
    extra_missing = [
        batch.missing[index][6] for batch in batches for index in range(batch.row_count)
    ]
    assert all(extra_missing)


def test_reader_rejects_an_unknown_sheet(testdata_path: Path) -> None:
    reader = ExcelSheetReader(
        io.BytesIO(testdata_path("observations.xlsx").read_bytes()),
        ExcelReadOptions(column_names=COLUMN_NAMES, sheet="Missing"),
    )
    with pytest.raises(ValidationError) as error:
        list(reader)
    assert error.value.details["sheet"] == "Missing"
    assert "Observations" in error.value.details["available_sheets"]


def test_reader_selects_the_first_sheet_by_default(testdata_path: Path) -> None:
    reader = ExcelSheetReader(
        io.BytesIO(testdata_path("observations.xlsx").read_bytes()),
        ExcelReadOptions(column_names=COLUMN_NAMES, mapped_columns=MAPPED_WITHOUT_FORMULAS),
    )
    batches = list(reader)
    assert reader.sheet_title == "Observations"
    assert count_rows(batches) == 4


def test_reader_batches_rows_at_the_requested_size(testdata_path: Path) -> None:
    reader = ExcelSheetReader(
        io.BytesIO(testdata_path("observations.xlsx").read_bytes()),
        ExcelReadOptions(
            column_names=COLUMN_NAMES,
            mapped_columns=MAPPED_WITHOUT_FORMULAS,
            batch_rows=2,
        ),
    )
    batches = list(reader)
    assert [batch.row_count for batch in batches] == [2, 2]
    assert [batch.first_row_index for batch in batches] == [0, 2]


def test_reader_options_are_validated() -> None:
    with pytest.raises(ValidationError):
        ExcelReadOptions(column_names=())
    with pytest.raises(ValidationError):
        ExcelReadOptions(column_names=("a", "a"))
    with pytest.raises(ValidationError):
        ExcelReadOptions(column_names=("a",), skip_leading_rows=-1)
    with pytest.raises(ValidationError):
        ExcelReadOptions(column_names=("a",), batch_rows=0)
    with pytest.raises(ValidationError):
        ExcelReadOptions(column_names=("a",), mapped_columns=("b",))


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ""),
        (True, "true"),
        (False, "false"),
        (12, "12"),
        (6.8, "6.8"),
        (0.00001, "1e-05"),
        (Decimal("12.40"), "12.40"),
        (datetime(2024, 1, 15, 9, 30), "2024-01-15T09:30:00"),
        (date(2024, 2, 12), "2024-02-12"),
        (time(9, 30), "09:30:00"),
        ("plain text", "plain text"),
    ],
)
def test_excel_cell_to_text_converts_stored_values(value: object, expected: str) -> None:
    assert excel_cell_to_text(value) == expected


def test_excel_cell_to_text_rejects_unsupported_values() -> None:
    with pytest.raises(UnsupportedCellValueError) as error:
        excel_cell_to_text(timedelta(hours=2))
    assert "timedelta" in str(error.value)
    with pytest.raises(UnsupportedCellValueError):
        excel_cell_to_text(object())
