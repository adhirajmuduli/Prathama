"""Read-only workbook reader with sheet, cell, formula, and archive limits.

A workbook is an untrusted container: it can carry macros, a decompression
bomb, a formula that the analyst never sees, or a value type that has no text
form. This module rejects each of those explicitly. The container is inspected
before OpenPyXL opens it, the sheet and cell ceilings are enforced while rows
are streamed, and a formula cell is rejected as data unless the deployment has
explicitly accepted cached values, in which case the substitution is recorded
as a cell issue.

Empty trailing cells are normal in a spreadsheet and are padded with a missing
marker; a row *wider* than the declared columns is a malformed table and is
rejected, which matches the behavior of the delimited reader.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, BinaryIO, Literal

import openpyxl
from openpyxl.utils.exceptions import InvalidFileException

from trendsmapp.constants import CSV_RECORD_BATCH_ROWS
from trendsmapp.errors import ParsingError, ValidationError
from trendsmapp.ingestion.chunking import TextBatch
from trendsmapp.ingestion.security import (
    ZipInspection,
    enforce_cell_ceiling,
    enforce_workbook_sheet_ceiling,
    enforce_zip_limits,
    inspect_zip_container,
    require_seekable,
)

__all__ = [
    "CellIssue",
    "ExcelReadOptions",
    "ExcelSheetReader",
    "SheetInfo",
    "WorkbookInspection",
    "excel_cell_to_text",
    "inspect_workbook",
    "read_excel_sheet_names",
]

CellIssueKind = Literal[
    "formula",
    "formula_without_cached_value",
    "error_cell",
    "unsupported_value_type",
    "missing_sampled_value",
]


class UnsupportedCellValueError(Exception):
    """Raised when a cell holds a value with no exact text representation."""

    def __init__(self, python_type: str) -> None:
        super().__init__(f"A cell of type '{python_type}' cannot be represented as text.")
        self.python_type = python_type


@dataclass(frozen=True, slots=True)
class SheetInfo:
    """One sheet of a workbook."""

    title: str
    declared_rows: int | None
    declared_columns: int | None


@dataclass(frozen=True, slots=True)
class WorkbookInspection:
    """The structural description of a workbook."""

    sheets: tuple[SheetInfo, ...]
    container: ZipInspection

    @property
    def sheet_count(self) -> int:
        """Return the number of sheets in the workbook."""
        return len(self.sheets)

    @property
    def declared_cells(self) -> int | None:
        """Return the total declared cell count, when every sheet declares it."""
        total = 0
        for sheet in self.sheets:
            if sheet.declared_rows is None or sheet.declared_columns is None:
                return None
            total += sheet.declared_rows * sheet.declared_columns
        return total


@dataclass(frozen=True, slots=True)
class CellIssue:
    """One cell that could not be used as data without a decision."""

    sheet: str
    row: int
    column: int
    column_name: str | None
    kind: CellIssueKind
    detail: str


@dataclass(frozen=True, slots=True)
class ExcelReadOptions:
    """The exact options a worksheet is read with."""

    column_names: tuple[str, ...]
    sheet: str | None = None
    skip_leading_rows: int = 0
    accept_cached_formula_values: bool = False
    batch_rows: int = CSV_RECORD_BATCH_ROWS
    mapped_columns: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if not self.column_names:
            raise ValidationError("A workbook read requires the column names.")
        if len(set(self.column_names)) != len(self.column_names):
            raise ValidationError("Column names must be unique.")
        if self.skip_leading_rows < 0:
            raise ValidationError("The number of skipped rows cannot be negative.")
        if self.batch_rows < 1:
            raise ValidationError("The batch size must be at least one row.")
        if self.mapped_columns is not None:
            unknown = set(self.mapped_columns) - set(self.column_names)
            if unknown:
                raise ValidationError(
                    "The mapped columns must be a subset of the declared columns.",
                    details={"unknown_columns": sorted(unknown)},
                )

    @property
    def mapping_is_strict(self) -> bool:
        """Return whether every declared column is treated as mapped data."""
        return self.mapped_columns is None

    def is_mapped(self, column_name: str) -> bool:
        """Return whether a column feeds the canonical dataset."""
        if self.mapped_columns is None:
            return True
        return column_name in self.mapped_columns


class ExcelSheetReader:
    """Streams one worksheet as text batches while enforcing the cell policy."""

    def __init__(self, stream: BinaryIO, options: ExcelReadOptions) -> None:
        require_seekable(stream, context="reading a workbook")
        self._stream = stream
        self._options = options
        self._issues: list[CellIssue] = []
        self._workbook: Any | None = None
        self._cached_workbook: Any | None = None
        self._sheet_title: str | None = None

    @property
    def issues(self) -> tuple[CellIssue, ...]:
        """Return every cell issue raised while streaming."""
        return tuple(self._issues)

    @property
    def sheet_title(self) -> str | None:
        """Return the title of the sheet that was read, once it is known."""
        return self._sheet_title

    def close(self) -> None:
        """Release both workbook handles."""
        for handle in (self._cached_workbook, self._workbook):
            closer = getattr(handle, "close", None)
            if callable(closer):
                closer()
        self._workbook = None
        self._cached_workbook = None

    def __iter__(self) -> Iterator[TextBatch]:
        """Yield the data rows of the sheet as text batches."""
        try:
            yield from self._stream_batches()
        finally:
            self.close()

    def _stream_batches(self) -> Iterator[TextBatch]:
        workbook = self._open_workbook(data_only=False)
        sheet_names = tuple(str(name) for name in workbook.sheetnames)
        enforce_workbook_sheet_ceiling(len(sheet_names))
        title = self._options.sheet or (sheet_names[0] if sheet_names else "")
        if title not in sheet_names:
            raise ValidationError(
                "The requested sheet does not exist in the workbook.",
                details={"sheet": title, "available_sheets": list(sheet_names)},
            )
        self._sheet_title = title
        worksheet = workbook[title]
        cached_rows: Iterator[tuple[object, ...]] | None = None
        if self._options.accept_cached_formula_values:
            cached_sheet = self._open_cached_worksheet(title)
            if cached_sheet is not None:
                cached_rows = iter(cached_sheet.iter_rows())

        columns = self._options.column_names
        width = len(columns)
        batch_rows: list[tuple[str, ...]] = []
        batch_missing: list[tuple[bool, ...]] = []
        emitted = 0
        physical_row = 0
        cells_seen = 0
        try:
            for cells in worksheet.iter_rows():
                cached_row = next(cached_rows, None) if cached_rows is not None else None
                physical_row += 1
                cells_seen += len(cells)
                enforce_cell_ceiling(cells_seen)
                if len(cells) > width:
                    raise ParsingError(
                        "A worksheet row has more cells than the declared columns.",
                        details={
                            "sheet": title,
                            "row": physical_row,
                            "cells": len(cells),
                            "columns": width,
                        },
                    )
                if physical_row <= self._options.skip_leading_rows:
                    continue
                row_text: list[str] = []
                row_missing: list[bool] = []
                for index in range(width):
                    cell = cells[index] if index < len(cells) else None
                    text, missing = self._read_cell(
                        cell=cell,
                        cached_cell=(
                            cached_row[index]
                            if cached_row is not None and index < len(cached_row)
                            else None
                        ),
                        column_name=columns[index],
                        row_number=physical_row,
                        sheet_title=title,
                    )
                    row_text.append(text)
                    row_missing.append(missing)
                batch_rows.append(tuple(row_text))
                batch_missing.append(tuple(row_missing))
                if len(batch_rows) >= self._options.batch_rows:
                    yield TextBatch(
                        columns=columns,
                        rows=tuple(batch_rows),
                        missing=tuple(batch_missing),
                        first_row_index=emitted,
                    )
                    emitted += len(batch_rows)
                    batch_rows = []
                    batch_missing = []
            if batch_rows:
                yield TextBatch(
                    columns=columns,
                    rows=tuple(batch_rows),
                    missing=tuple(batch_missing),
                    first_row_index=emitted,
                )
        finally:
            self.close()

    def _read_cell(
        self,
        *,
        cell: object,
        cached_cell: object | None,
        column_name: str,
        row_number: int,
        sheet_title: str,
    ) -> tuple[str, bool]:
        """Return the text and the missing marker of one worksheet cell."""
        if cell is None:
            return "", True
        data_type = getattr(cell, "data_type", None)
        value = getattr(cell, "value", None)
        if data_type == "f":
            return self._read_formula_cell(
                cached_cell=cached_cell,
                column_name=column_name,
                row_number=row_number,
                sheet_title=sheet_title,
            )
        if data_type == "e":
            return self._read_error_cell(
                value=value,
                column_name=column_name,
                row_number=row_number,
                sheet_title=sheet_title,
            )
        if value is None:
            return "", True
        try:
            return excel_cell_to_text(value), False
        except UnsupportedCellValueError as exc:
            self._issues.append(
                CellIssue(
                    sheet=sheet_title,
                    row=row_number,
                    column=self._column_index(column_name),
                    column_name=column_name,
                    kind="unsupported_value_type",
                    detail=exc.python_type,
                )
            )
            if self._options.is_mapped(column_name):
                raise ParsingError(
                    f"The cell at row {row_number} of column '{column_name}' holds a "
                    f"value of type '{exc.python_type}', which has no exact text form.",
                    details={
                        "sheet": sheet_title,
                        "row": row_number,
                        "column": column_name,
                        "value_type": exc.python_type,
                    },
                ) from exc
            return "", True

    def _read_formula_cell(
        self,
        *,
        cached_cell: object | None,
        column_name: str,
        row_number: int,
        sheet_title: str,
    ) -> tuple[str, bool]:
        """Apply the formula policy to one formula cell."""
        column_index = self._column_index(column_name)
        if not self._options.accept_cached_formula_values:
            self._issues.append(
                CellIssue(
                    sheet=sheet_title,
                    row=row_number,
                    column=column_index,
                    column_name=column_name,
                    kind="formula",
                    detail="the cell holds a formula and cached values are not accepted",
                )
            )
            if self._options.is_mapped(column_name):
                raise ParsingError(
                    f"The cell at row {row_number} of column '{column_name}' holds a "
                    "formula. Formulas are rejected as data unless the deployment "
                    "explicitly accepts cached values.",
                    details={
                        "sheet": sheet_title,
                        "row": row_number,
                        "column": column_name,
                        "reason": "formula_cell",
                    },
                )
            return "", True
        cached_value = getattr(cached_cell, "value", None) if cached_cell is not None else None
        if cached_value is None:
            self._issues.append(
                CellIssue(
                    sheet=sheet_title,
                    row=row_number,
                    column=column_index,
                    column_name=column_name,
                    kind="formula_without_cached_value",
                    detail="the formula has no cached value in the file",
                )
            )
            if self._options.is_mapped(column_name):
                raise ParsingError(
                    f"The cell at row {row_number} of column '{column_name}' holds a "
                    "formula with no cached value, so no value can be recovered.",
                    details={
                        "sheet": sheet_title,
                        "row": row_number,
                        "column": column_name,
                        "reason": "formula_without_cached_value",
                    },
                )
            return "", True
        self._issues.append(
            CellIssue(
                sheet=sheet_title,
                row=row_number,
                column=column_index,
                column_name=column_name,
                kind="formula",
                detail="the cached value of the formula was used",
            )
        )
        try:
            return excel_cell_to_text(cached_value), False
        except UnsupportedCellValueError as exc:
            raise ParsingError(
                f"The cached value at row {row_number} of column '{column_name}' has no "
                "exact text form.",
                details={
                    "sheet": sheet_title,
                    "row": row_number,
                    "column": column_name,
                    "value_type": exc.python_type,
                },
            ) from exc

    def _read_error_cell(
        self,
        *,
        value: object,
        column_name: str,
        row_number: int,
        sheet_title: str,
    ) -> tuple[str, bool]:
        """Reject an error cell as data; an error is not a measurement."""
        error_code = value if isinstance(value, str) else "an error value"
        self._issues.append(
            CellIssue(
                sheet=sheet_title,
                row=row_number,
                column=self._column_index(column_name),
                column_name=column_name,
                kind="error_cell",
                detail=error_code,
            )
        )
        if self._options.is_mapped(column_name):
            raise ParsingError(
                f"The cell at row {row_number} of column '{column_name}' holds the "
                f"spreadsheet error {error_code}. An error cell cannot be a value.",
                details={
                    "sheet": sheet_title,
                    "row": row_number,
                    "column": column_name,
                    "reason": "error_cell",
                    "error_code": error_code,
                },
            )
        return "", True

    def _column_index(self, column_name: str) -> int:
        """Return the zero-based position of a declared column."""
        try:
            return self._options.column_names.index(column_name)
        except ValueError:
            return -1

    def _open_workbook(self, *, data_only: bool) -> Any:
        """Open the workbook in read-only mode after the container checks."""
        require_seekable(self._stream, context="reading a workbook")
        self._stream.seek(0)
        container = inspect_zip_container(self._stream)
        enforce_zip_limits(container, label="workbook")
        self._stream.seek(0)
        try:
            workbook = openpyxl.load_workbook(
                self._stream,
                read_only=True,
                data_only=data_only,
                keep_links=False,
                rich_text=False,
            )
        except (InvalidFileException, KeyError, OSError, TypeError, ValueError) as exc:
            raise ParsingError(
                "The workbook container could not be read as a spreadsheet.",
                details={"reason": "unreadable_workbook", "error_kind": type(exc).__name__},
            ) from exc
        if data_only:
            self._cached_workbook = workbook
        else:
            self._workbook = workbook
        return workbook

    def _open_cached_worksheet(self, title: str) -> Any | None:
        """Open the cached-value view of the sheet, when the file provides one."""
        workbook = self._open_workbook(data_only=True)
        sheet_names = tuple(str(name) for name in workbook.sheetnames)
        if title not in sheet_names:
            return None
        return workbook[title]


def inspect_workbook(stream: BinaryIO) -> WorkbookInspection:
    """Return the sheets and the container verdict of a workbook."""
    require_seekable(stream, context="inspecting a workbook")
    stream.seek(0)
    container = inspect_zip_container(stream)
    enforce_zip_limits(container, label="workbook")
    stream.seek(0)
    try:
        workbook = openpyxl.load_workbook(
            stream, read_only=True, data_only=False, keep_links=False, rich_text=False
        )
    except (InvalidFileException, KeyError, OSError, TypeError, ValueError) as exc:
        raise ParsingError(
            "The workbook container could not be read as a spreadsheet.",
            details={"reason": "unreadable_workbook", "error_kind": type(exc).__name__},
        ) from exc
    sheets: list[SheetInfo] = []
    try:
        enforce_workbook_sheet_ceiling(len(workbook.sheetnames))
        for title in workbook.sheetnames:
            worksheet = workbook[title]
            rows = _safe_dimension(worksheet, "max_row")
            columns = _safe_dimension(worksheet, "max_column")
            sheets.append(SheetInfo(title=str(title), declared_rows=rows, declared_columns=columns))
    finally:
        workbook.close()
    inspection = WorkbookInspection(sheets=tuple(sheets), container=container)
    declared = inspection.declared_cells
    if declared is not None:
        enforce_cell_ceiling(declared)
    return inspection


def read_excel_sheet_names(stream: BinaryIO) -> tuple[str, ...]:
    """Return the sheet names of a workbook in workbook order."""
    return tuple(sheet.title for sheet in inspect_workbook(stream).sheets)


def excel_cell_to_text(value: object) -> str:
    """Return the exact text form of a worksheet value.

    The conversion is total for the value types OpenPyXL produces for stored
    data. Dates and timestamps become ISO 8601 text so that the timestamp
    parser is the single place where a temporal convention is applied.
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
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    if isinstance(value, timedelta):
        raise UnsupportedCellValueError("timedelta")
    if isinstance(value, str):
        return value
    raise UnsupportedCellValueError(type(value).__name__)


def _safe_dimension(worksheet: object, attribute: str) -> int | None:
    """Return a declared sheet dimension when the file provides one."""
    try:
        value = getattr(worksheet, attribute)
    except Exception:  # noqa: BLE001 - a missing dimension is not an error
        return None
    if isinstance(value, int) and value > 0:
        return value
    return None
