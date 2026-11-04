"""Parse orchestration: format dispatch, mapping, conversion, and reporting.

The parser is the seam between an untrusted upload and the canonical pipeline.
It never interprets a scientific value; it turns bytes into the canonical long
schema with every source convention preserved as text, and it reports exactly
what it saw so the analyst can audit the decision the pipeline is about to
make on their behalf.

One pass, two phases:

- :func:`probe_parse` inspects the first rows only. It answers what the file
  looks like and proposes a column mapping for the analyst to confirm.
- :class:`ParseSession` reads the whole table under a confirmed mapping and
  produces long-schema batches plus a :class:`ParseReport`. A failed parse
  still produces its report: the failure is recorded in it, and the exception
  is re-raised for the worker to handle.

The report is a stored artifact document. Its schema is versioned, additive
within a version, and every field is derived from what actually happened —
never from what was expected.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, BinaryIO, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from trendsmapp.constants import SNIFF_SAMPLE_ROWS
from trendsmapp.contracts.versions import APPLICATION_VERSION, ARTIFACT_SCHEMA_VERSION
from trendsmapp.domain.enums import ColumnRole, FileFormat, LayoutKind
from trendsmapp.errors import ParsingError, TrendsmappError
from trendsmapp.ingestion.chunking import TextBatch
from trendsmapp.ingestion.column_mapping import (
    ColumnMapping,
    ProposedMapping,
    ResolvedMapping,
    propose_mapping,
    resolve_mapping,
    validate_mapping,
)
from trendsmapp.ingestion.csv_reader import CsvReadOptions, read_csv_batches
from trendsmapp.ingestion.excel_reader import (
    ExcelReadOptions,
    ExcelSheetReader,
    WorkbookInspection,
    excel_cell_to_text,
    inspect_workbook,
)
from trendsmapp.ingestion.file_types import FileTypeVerdict, inspect_file_type
from trendsmapp.ingestion.parquet_reader import (
    ParquetInspection,
    inspect_parquet,
    read_parquet_batches,
)
from trendsmapp.ingestion.security import (
    enforce_column_ceiling,
    enforce_row_ceiling,
    require_seekable,
)
from trendsmapp.ingestion.sniffing import (
    SniffResult,
    sniff,
    sniff_delimited_bytes,
)
from trendsmapp.ingestion.wide_to_long import LONG_SCHEMA_FIELDS, WideToLongIterator

__all__ = [
    "ParseCellIssue",
    "ParseFailure",
    "ParseProbe",
    "ParseReport",
    "ParseSession",
    "probe_parse",
]

#: How many leading bytes are read for file-type detection and sniffing.
_HEAD_BYTES: Final[int] = 64 * 1024

FormulaPolicy = Literal["reject", "accept_cached"]


@dataclass(frozen=True, slots=True)
class ParseProbe:
    """What the first rows of a table look like, with a proposed mapping."""

    file_type: FileTypeVerdict
    sniff: SniffResult
    workbook: WorkbookInspection | None
    parquet: ParquetInspection | None
    sheet_names: tuple[str, ...]
    proposed_mapping: ColumnMapping
    proposal_warnings: tuple[str, ...]
    numeric_fields: frozenset[str]
    date_fields: frozenset[str]

    @property
    def fields(self) -> tuple[str, ...]:
        """Return the field names the probe identified."""
        return self.sniff.fields

    @property
    def layout(self) -> LayoutKind:
        """Return the layout the probe's evidence supports."""
        return self.sniff.layout.layout


class ParseCellIssue(BaseModel):
    """One cell that could not be used as data without a decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sheet: str | None
    row: int
    column: int
    column_name: str | None
    kind: str
    detail: str


class ParseFailure(BaseModel):
    """The structured failure a parse ended with."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ParseReport(BaseModel):
    """The stored document describing one parse.

    Every field is a fact about the parse: what was detected, what was
    decided, what was counted, and what failed. The report never contains file
    content beyond the column names the analyst mapped.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = ARTIFACT_SCHEMA_VERSION
    application_version: str = APPLICATION_VERSION
    filename: str
    extension: str
    file_format: str
    declared_content_type: str | None = None
    content_type_accepted: bool | None = None
    source_size_bytes: int | None = None
    source_sha256: str | None = None
    detected_format: str | None = None
    encoding: str | None = None
    delimiter: str | None = None
    has_header: bool = False
    header_row_index: int | None = None
    fields: tuple[str, ...] = ()
    decimal_style: str = "point"
    layout: str = "unknown"
    layout_confidence: float = 0.0
    layout_evidence: tuple[str, ...] = ()
    layout_warnings: tuple[str, ...] = ()
    sniff_warnings: tuple[str, ...] = ()
    sheet: str | None = None
    sheet_names: tuple[str, ...] = ()
    row_count: int = 0
    column_count: int = 0
    mapping: ColumnMapping
    mapping_warnings: tuple[str, ...] = ()
    formula_policy: FormulaPolicy = "reject"
    formula_cells_seen: int = 0
    formula_cells_used: int = 0
    error_cells_seen: int = 0
    cell_issues: tuple[ParseCellIssue, ...] = ()
    skipped_leading_rows: int = 0
    wide_records_emitted: int | None = None
    wide_source_rows_seen: int | None = None
    wide_source_rows_skipped: int | None = None
    completed: bool = False
    failure: ParseFailure | None = None


@dataclass(frozen=True, slots=True)
class _TablePlan:
    """Everything the full read needs, derived once from the probe path."""

    sniff: SniffResult
    resolved: ResolvedMapping
    mapping_warnings: tuple[str, ...]
    workbook: WorkbookInspection | None
    parquet: ParquetInspection | None
    sheet_names: tuple[str, ...]
    sheet: str | None


def _read_head(stream: BinaryIO) -> bytes:
    """Read a bounded prefix of a seekable stream and rewind it."""
    require_seekable(stream, context="parsing a table")
    stream.seek(0)
    head = stream.read(_HEAD_BYTES)
    stream.seek(0)
    return head


def _evidence_fields(sniffed: SniffResult) -> tuple[frozenset[str], frozenset[str]]:
    """Return the numeric and date-like fields the sample supports."""
    numeric = frozenset(column.name for column in sniffed.columns if column.is_numeric)
    dated = frozenset(column.name for column in sniffed.columns if column.is_date_like)
    return numeric, dated


def _sniff_table(
    stream: BinaryIO,
    verdict: FileTypeVerdict,
    *,
    sheet: str | None,
    sample_rows: int,
) -> tuple[SniffResult, WorkbookInspection | None, ParquetInspection | None, tuple[str, ...]]:
    """Inspect the first rows of a table, whatever its format."""
    if verdict.format in {FileFormat.CSV, FileFormat.TSV}:
        sniffed = sniff_delimited_bytes(
            _read_head(stream), file_format=verdict.format, sample_rows=sample_rows
        )
        return sniffed, None, None, ()

    if verdict.format is FileFormat.XLSX:
        workbook = inspect_workbook(stream)
        sheet_names = tuple(item.title for item in workbook.sheets)
        selected = sheet or (sheet_names[0] if sheet_names else "")
        rows = _probe_workbook_rows(stream, selected, sample_rows)
        sniffed = sniff(rows, file_format=FileFormat.XLSX, sample_truncated=False)
        return sniffed, workbook, None, sheet_names

    parquet = inspect_parquet(stream)
    rows = _probe_parquet_rows(stream, parquet, sample_rows)
    sniffed = sniff(
        rows,
        file_format=FileFormat.PARQUET,
        declared_fields=parquet.column_names,
        sample_truncated=False,
    )
    return sniffed, None, parquet, ()


def _probe_workbook_rows(
    stream: BinaryIO, sheet: str, sample_rows: int
) -> tuple[tuple[str, ...], ...]:
    """Read the first rows of a worksheet as evidence, tolerating formulas.

    The probe reads cells through :func:`excel_cell_to_text` without the
    formula policy: a formula cell becomes its formula text, which is enough
    evidence to detect the header and the layout. The full parse enforces the
    policy and reports every such cell.
    """
    import openpyxl

    stream.seek(0)
    try:
        workbook = openpyxl.load_workbook(
            stream, read_only=True, data_only=False, keep_links=False, rich_text=False
        )
    except (OSError, ValueError, KeyError) as exc:
        raise ParsingError(
            "The workbook could not be opened for inspection.",
            details={"reason": "unreadable_workbook"},
        ) from exc
    try:
        worksheet = workbook[sheet]
        rows: list[tuple[str, ...]] = []
        width = 0
        for row in worksheet.iter_rows(max_row=sample_rows):
            cells = [excel_cell_to_text(cell.value) for cell in row]
            width = max(width, len(cells))
            rows.append(tuple(cells))
        padded = tuple(row + ("",) * (width - len(row)) for row in rows)
        return padded
    finally:
        workbook.close()


def _probe_parquet_rows(
    stream: BinaryIO, parquet: ParquetInspection, sample_rows: int
) -> tuple[tuple[str, ...], ...]:
    """Read the first rows of a Parquet file as evidence."""
    rows: list[tuple[str, ...]] = []
    for batch in read_parquet_batches(
        stream, columns=parquet.column_names, batch_rows=min(sample_rows, 10_000)
    ):
        rows.extend(batch.rows)
        if len(rows) >= sample_rows:
            break
    return tuple(rows[:sample_rows])


def _build_plan(
    *,
    stream: BinaryIO,
    filename: str,
    content_type: str | None,
    mapping: ColumnMapping,
    sheet: str | None,
    sample_rows: int,
) -> _TablePlan:
    """Derive the full-read plan: evidence, validation, and resolution."""
    head = _read_head(stream)
    verdict = inspect_file_type(filename=filename, content_type=content_type, head=head)
    sniffed, workbook, parquet, sheet_names = _sniff_table(
        stream, verdict, sheet=sheet, sample_rows=sample_rows
    )
    numeric_fields, date_fields = _evidence_fields(sniffed)
    validation = validate_mapping(
        mapping,
        fields=sniffed.fields,
        numeric_fields=numeric_fields,
        date_fields=date_fields,
    )
    enforce_column_ceiling(len(sniffed.fields))
    resolved = resolve_mapping(mapping, fields=sniffed.fields, has_header=sniffed.has_header)
    selected_sheet = sheet
    if verdict.format is FileFormat.XLSX:
        selected_sheet = sheet or (sheet_names[0] if sheet_names else None)
    return _TablePlan(
        sniff=sniffed,
        resolved=resolved,
        mapping_warnings=validation.warnings,
        workbook=workbook,
        parquet=parquet,
        sheet_names=sheet_names,
        sheet=selected_sheet,
    )


def probe_parse(
    stream: BinaryIO,
    *,
    filename: str,
    content_type: str | None = None,
    sheet: str | None = None,
    sample_rows: int = SNIFF_SAMPLE_ROWS,
) -> ParseProbe:
    """Inspect the first rows of a table and propose a column mapping.

    The probe reads a bounded sample. It never interprets a value and never
    enforces the formula policy: its output is evidence and a proposal, and the
    analyst confirms both before a full parse happens.
    """
    head = _read_head(stream)
    verdict = inspect_file_type(filename=filename, content_type=content_type, head=head)
    sniffed, workbook, parquet, sheet_names = _sniff_table(
        stream, verdict, sheet=sheet, sample_rows=sample_rows
    )
    numeric_fields, date_fields = _evidence_fields(sniffed)
    proposal: ProposedMapping = propose_mapping(
        sniffed.fields,
        numeric_fields=numeric_fields,
        date_fields=date_fields,
        layout=sniffed.layout.layout,
    )
    return ParseProbe(
        file_type=verdict,
        sniff=sniffed,
        workbook=workbook,
        parquet=parquet,
        sheet_names=sheet_names,
        proposed_mapping=proposal.mapping,
        proposal_warnings=proposal.warnings,
        numeric_fields=numeric_fields,
        date_fields=date_fields,
    )


class ParseSession:
    """Reads one table under a confirmed mapping and reports the parse.

    The session is single-use: iterate it once, then read :attr:`report`.
    Batches carry the canonical long schema, so normalization downstream never
    sees the source layout again.
    """

    def __init__(
        self,
        stream: BinaryIO,
        *,
        filename: str,
        content_type: str | None,
        mapping: ColumnMapping,
        source_size_bytes: int | None = None,
        source_sha256: str | None = None,
        sheet: str | None = None,
        accept_cached_formula_values: bool = False,
        batch_rows: int = 200,
    ) -> None:
        self._stream = stream
        self._filename = filename
        self._content_type = content_type
        self._mapping = mapping
        self._source_size_bytes = source_size_bytes
        self._source_sha256 = source_sha256
        self._sheet = sheet
        self._accept_cached = accept_cached_formula_values
        self._batch_rows = batch_rows
        self._plan: _TablePlan | None = None
        self._verdict: FileTypeVerdict | None = None
        self._row_count = 0
        self._reader_warnings: list[str] = []
        self._cell_issues: list[ParseCellIssue] = []
        self._formula_cells_seen = 0
        self._formula_cells_used = 0
        self._error_cells_seen = 0
        self._wide_records: tuple[int, int, int] | None = None
        self._completed = False
        self._failure: ParseFailure | None = None
        self._started = False

    @property
    def report(self) -> ParseReport:
        """Return the report of the parse, complete or failed.

        A failure that happens before the table plan exists — a mapping that
        does not match the table, for example — still produces a report: it
        records the failure, the verdict, and nothing it does not know.
        """
        plan = self._plan
        verdict = self._verdict
        if not self._started:
            raise ParsingError(
                "The parse session was never started, so there is no report.",
                details={"reason": "session_not_started"},
            )
        if plan is None or verdict is None:
            return ParseReport(
                filename=self._filename,
                extension="unknown",
                file_format="unknown",
                mapping=self._mapping,
                completed=False,
                failure=self._failure,
            )
        sniffed = plan.sniff
        wide_records = self._wide_records
        return ParseReport(
            filename=self._filename,
            extension=verdict.extension,
            file_format=verdict.format.value,
            declared_content_type=verdict.content_type,
            content_type_accepted=verdict.content_type_accepted,
            source_size_bytes=self._source_size_bytes,
            source_sha256=self._source_sha256,
            detected_format=(
                verdict.magic_format.value if verdict.magic_format is not None else None
            ),
            encoding=sniffed.encoding,
            delimiter=sniffed.delimiter,
            has_header=sniffed.has_header,
            header_row_index=sniffed.header_row_index,
            fields=sniffed.fields,
            decimal_style=sniffed.decimal_style.value,
            layout=sniffed.layout.layout.value,
            layout_confidence=sniffed.layout.confidence,
            layout_evidence=sniffed.layout.evidence,
            layout_warnings=sniffed.layout.warnings,
            sniff_warnings=sniffed.warnings,
            sheet=plan.sheet,
            sheet_names=plan.sheet_names,
            row_count=self._row_count,
            column_count=len(sniffed.fields),
            mapping=self._mapping,
            mapping_warnings=plan.mapping_warnings,
            formula_policy="accept_cached" if self._accept_cached else "reject",
            formula_cells_seen=self._formula_cells_seen,
            formula_cells_used=self._formula_cells_used,
            error_cells_seen=self._error_cells_seen,
            cell_issues=tuple(self._cell_issues),
            skipped_leading_rows=1 if sniffed.has_header else 0,
            wide_records_emitted=wide_records[0] if wide_records else None,
            wide_source_rows_seen=wide_records[1] if wide_records else None,
            wide_source_rows_skipped=wide_records[2] if wide_records else None,
            completed=self._completed,
            failure=self._failure,
        )

    def __iter__(self) -> Iterator[TextBatch]:
        """Yield canonical long-schema batches for the whole table."""
        if self._started:
            raise ParsingError(
                "A parse session can only be iterated once.",
                details={"reason": "session_already_started"},
            )
        self._started = True
        try:
            yield from self._parse()
        except TrendsmappError as exc:
            self._failure = ParseFailure(
                code=exc.code, message=exc.message, details=dict(exc.details)
            )
            raise
        self._completed = True

    def _parse(self) -> Iterator[TextBatch]:
        """Dispatch to the format reader and convert to the long schema."""
        head = _read_head(self._stream)
        self._verdict = inspect_file_type(
            filename=self._filename, content_type=self._content_type, head=head
        )
        self._plan = _build_plan(
            stream=self._stream,
            filename=self._filename,
            content_type=self._content_type,
            mapping=self._mapping,
            sheet=self._sheet,
            sample_rows=SNIFF_SAMPLE_ROWS,
        )
        plan = self._plan
        verdict = self._verdict
        if verdict.format in {FileFormat.CSV, FileFormat.TSV}:
            yield from self._parse_delimited(plan)
        elif verdict.format is FileFormat.XLSX:
            yield from self._parse_workbook(plan)
        else:
            yield from self._parse_parquet(plan)

    def _parse_delimited(self, plan: _TablePlan) -> Iterator[TextBatch]:
        """Read a delimited table and convert it to the long schema."""
        sniffed = plan.sniff
        options = CsvReadOptions(
            column_names=sniffed.fields,
            delimiter=sniffed.delimiter or ",",
            encoding=sniffed.encoding or "utf-8",
            skip_leading_rows=1 if sniffed.has_header else 0,
            batch_rows=self._batch_rows,
        )
        batches = read_csv_batches(self._stream, options)
        yield from self._convert_to_long(batches, plan, source_sheet="")

    def _parse_workbook(self, plan: _TablePlan) -> Iterator[TextBatch]:
        """Read a worksheet and convert it to the long schema."""
        sniffed = plan.sniff
        sheet = plan.sheet or (plan.sheet_names[0] if plan.sheet_names else "")
        resolved = plan.resolved
        mapped_columns = tuple(
            field
            for field, role in resolved.role_by_field.items()
            if role is not ColumnRole.IGNORED
        )
        reader = ExcelSheetReader(
            self._stream,
            ExcelReadOptions(
                column_names=sniffed.fields,
                sheet=sheet,
                skip_leading_rows=1 if sniffed.has_header else 0,
                accept_cached_formula_values=self._accept_cached,
                batch_rows=self._batch_rows,
                mapped_columns=mapped_columns,
            ),
        )
        batches = iter(reader)
        try:
            yield from self._convert_to_long(batches, plan, source_sheet=sheet)
        finally:
            self._collect_cell_issues(reader)

    def _parse_parquet(self, plan: _TablePlan) -> Iterator[TextBatch]:
        """Read a Parquet table and convert it to the long schema."""
        sniffed = plan.sniff
        parquet = plan.parquet
        if parquet is None:
            raise ParsingError(
                "The Parquet inspection is missing from the parse plan.",
                details={"reason": "missing_inspection"},
            )
        batches = read_parquet_batches(
            self._stream,
            columns=sniffed.fields,
            batch_rows=min(self._batch_rows, 100_000),
            skip_leading_rows=1 if sniffed.has_header else 0,
        )
        yield from self._convert_to_long(batches, plan, source_sheet="")

    def _convert_to_long(
        self,
        batches: Iterator[TextBatch],
        plan: _TablePlan,
        *,
        source_sheet: str,
    ) -> Iterator[TextBatch]:
        """Route batches through the wide converter or the long reindex."""
        if plan.resolved.mapping.layout is LayoutKind.WIDE:
            converter = WideToLongIterator(
                batches=batches,
                resolved=plan.resolved,
                source_sheet=source_sheet,
                batch_rows=self._batch_rows,
            )
            for batch in converter:
                self._row_count += batch.row_count
                enforce_row_ceiling(self._row_count)
                yield batch
            stats = converter.stats
            self._wide_records = (
                stats.records_emitted,
                stats.source_rows_seen,
                stats.source_rows_skipped,
            )
            return
        for batch in batches:
            converted = self._reindex_long(batch, plan, source_sheet=source_sheet)
            self._row_count += converted.row_count
            enforce_row_ceiling(self._row_count)
            yield converted

    def _reindex_long(self, batch: TextBatch, plan: _TablePlan, *, source_sheet: str) -> TextBatch:
        """Reindex one source batch into the canonical long schema."""
        resolved = plan.resolved
        mapping = resolved.mapping
        indices: dict[str, int | None] = {}
        for role, long_field in _ROLE_TO_LONG_FIELD.items():
            field = resolved.field_of_role(role)
            indices[long_field] = batch.columns.index(field) if field else None
        unit_index = indices["unit"]
        parameter_index = indices["parameter"]
        default_unit = mapping.default_unit or ""
        default_parameter = mapping.default_parameter or ""
        rows: list[tuple[str, ...]] = []
        missing: list[tuple[bool, ...]] = []
        for offset, source_row in enumerate(batch.rows):
            source_missing = batch.missing[offset]
            physical_row = resolved.long_row_offset + batch.first_row_index + offset
            row_text: list[str] = []
            row_missing: list[bool] = []
            for long_field in LONG_SCHEMA_FIELDS:
                if long_field == "source_row":
                    row_text.append(str(physical_row))
                    row_missing.append(False)
                    continue
                if long_field == "source_sheet":
                    row_text.append(source_sheet)
                    row_missing.append(source_sheet == "")
                    continue
                if long_field == "unit":
                    column_unit = source_row[unit_index] if unit_index is not None else ""
                    unit = column_unit or default_unit
                    row_text.append(unit)
                    row_missing.append(unit == "")
                    continue
                if long_field == "parameter":
                    column_parameter = (
                        source_row[parameter_index] if parameter_index is not None else ""
                    )
                    parameter = column_parameter or default_parameter
                    row_text.append(parameter)
                    row_missing.append(parameter == "")
                    continue
                index = indices[long_field]
                if index is None:
                    row_text.append("")
                    row_missing.append(True)
                    continue
                row_text.append(source_row[index])
                row_missing.append(source_missing[index])
            rows.append(tuple(row_text))
            missing.append(tuple(row_missing))
        return TextBatch(
            columns=LONG_SCHEMA_FIELDS,
            rows=tuple(rows),
            missing=tuple(missing),
            first_row_index=batch.first_row_index,
        )

    def _collect_cell_issues(self, reader: ExcelSheetReader) -> None:
        """Fold the reader's cell issues into the report counters."""
        for issue in reader.issues:
            self._cell_issues.append(
                ParseCellIssue(
                    sheet=issue.sheet,
                    row=issue.row,
                    column=issue.column,
                    column_name=issue.column_name,
                    kind=issue.kind,
                    detail=issue.detail,
                )
            )
            if issue.kind in {"formula", "formula_without_cached_value"}:
                self._formula_cells_seen += 1
                if issue.detail == "the cached value of the formula was used":
                    self._formula_cells_used += 1
            elif issue.kind == "error_cell":
                self._error_cells_seen += 1


_ROLE_TO_LONG_FIELD: Final[dict[ColumnRole, str]] = {
    ColumnRole.STATION: "station",
    ColumnRole.TIMESTAMP: "sampled_at",
    ColumnRole.PARAMETER: "parameter",
    ColumnRole.VALUE: "value",
    ColumnRole.UNIT: "unit",
    ColumnRole.QUALIFIER: "qualifier",
    ColumnRole.LATITUDE: "latitude",
    ColumnRole.LONGITUDE: "longitude",
    ColumnRole.DEPTH: "depth_m",
    ColumnRole.SECTOR: "sector",
}
