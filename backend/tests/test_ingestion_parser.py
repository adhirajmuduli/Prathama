"""Tests for parse orchestration: probe, mapping application, and reporting."""

from __future__ import annotations

import io
from pathlib import Path
from typing import BinaryIO

import pytest

from trendsmapp.domain.enums import ColumnRole, FileFormat, LayoutKind
from trendsmapp.errors import ParsingError, ValidationError
from trendsmapp.ingestion.chunking import count_rows
from trendsmapp.ingestion.column_mapping import ColumnMapping, MappedColumn
from trendsmapp.ingestion.parser import ParseSession, probe_parse
from trendsmapp.ingestion.wide_to_long import LONG_SCHEMA_FIELDS


def _open(testdata_path: Path, name: str) -> BinaryIO:
    return io.BytesIO(testdata_path(name).read_bytes())


def _complete_long(probe: object, **overrides: object) -> ColumnMapping:
    base = probe.proposed_mapping.model_dump()  # type: ignore[attr-defined]
    base.update(overrides)
    return ColumnMapping.model_validate(base)


def _rerole(mapping: ColumnMapping, column: str, role: ColumnRole) -> ColumnMapping:
    columns = [
        item.model_copy(update={"role": role}) if item.column == column else item
        for item in mapping.columns
    ]
    return ColumnMapping.model_validate(
        {**mapping.model_dump(), "columns": [item.model_dump() for item in columns]}
    )


def test_probe_describes_the_long_fixture(testdata_path: Path) -> None:
    probe = probe_parse(
        _open(testdata_path, "long_observations.csv"),
        filename="long_observations.csv",
        content_type="text/csv",
    )
    assert probe.file_type.format is FileFormat.CSV
    assert probe.fields == (
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
    assert probe.layout is LayoutKind.LONG
    assert probe.sniff.layout.confidence == pytest.approx(0.9)
    assert probe.numeric_fields == {"latitude", "longitude", "value", "depth_m"}
    assert probe.date_fields == {"sampled_at"}
    proposal_roles = {item.column: item.role for item in probe.proposed_mapping.columns}
    assert proposal_roles["station"] is ColumnRole.STATION
    assert proposal_roles["value"] is ColumnRole.VALUE
    assert proposal_roles["notes"] is ColumnRole.IGNORED
    assert probe.proposal_warnings == ()


def test_probe_does_not_consume_or_break_the_stream(testdata_path: Path) -> None:
    stream = _open(testdata_path, "long_observations.csv")
    probe_parse(stream, filename="long_observations.csv")
    assert stream.tell() == 0
    assert stream.read(12) == b"station,lati"


def test_probe_rejects_a_mislabeled_file(testdata_path: Path) -> None:
    with pytest.raises(ValidationError):
        probe_parse(_open(testdata_path, "not_a_workbook.xlsx"), filename="not_a_workbook.xlsx")


def test_probe_lists_workbook_sheets(testdata_path: Path) -> None:
    probe = probe_parse(_open(testdata_path, "observations.xlsx"), filename="observations.xlsx")
    assert probe.sheet_names == ("Observations", "Notes")
    assert probe.workbook is not None
    assert probe.workbook.sheet_count == 2


def test_probe_names_schema_columns_for_parquet(testdata_path: Path) -> None:
    probe = probe_parse(
        _open(testdata_path, "observations.parquet"), filename="observations.parquet"
    )
    assert probe.fields == (
        "station",
        "value",
        "sampled_at",
        "collected_on",
        "sample_count",
        "is_valid",
        "salinity",
        "notes",
    )
    assert probe.sniff.has_header is False
    assert probe.sniff.header_row_index is None


def test_parse_long_csv_produces_the_canonical_schema(testdata_path: Path) -> None:
    probe = probe_parse(
        _open(testdata_path, "long_observations.csv"),
        filename="long_observations.csv",
        content_type="text/csv",
    )
    mapping = _complete_long(probe)
    session = ParseSession(
        _open(testdata_path, "long_observations.csv"),
        filename="long_observations.csv",
        content_type="text/csv",
        mapping=mapping,
        source_size_bytes=998,
        source_sha256="a" * 64,
        batch_rows=5,
    )
    batches = list(session)
    report = session.report

    assert count_rows(batches) == 12
    assert [batch.row_count for batch in batches] == [5, 5, 2]
    assert all(batch.columns == LONG_SCHEMA_FIELDS for batch in batches)
    first = batches[0].rows[0]
    assert first == (
        "St. A",
        "2024-01-15T09:30:00Z",
        "dissolved_oxygen",
        "6.8",
        "mg/L",
        "",
        "19.7350",
        "85.4700",
        "0.5",
        "",
        "2",
        "",
    )
    censored_index = 2
    assert batches[0].rows[censored_index][4] == "mg/L"
    assert batches[0].rows[censored_index][3] == "<0.01"
    assert batches[0].rows[censored_index][5] == "below_detection_limit"

    assert report.completed is True
    assert report.failure is None
    assert report.row_count == 12
    assert report.column_count == 10
    assert report.layout == "long"
    assert report.formula_policy == "reject"
    assert report.skipped_leading_rows == 1
    assert report.source_size_bytes == 998
    assert report.source_sha256 == "a" * 64
    assert report.sheet is None
    assert report.mapping == mapping
    assert report.mapping_warnings == ()
    assert report.wide_records_emitted is None


def test_parse_uses_the_unit_column_before_the_default(testdata_path: Path) -> None:
    probe = probe_parse(
        _open(testdata_path, "long_observations.csv"),
        filename="long_observations.csv",
        content_type="text/csv",
    )
    mapping = _complete_long(probe, default_unit="fallback_unit")
    session = ParseSession(
        _open(testdata_path, "long_observations.csv"),
        filename="long_observations.csv",
        content_type=None,
        mapping=mapping,
    )
    batches = list(session)
    units = {
        row[2]: row[LONG_SCHEMA_FIELDS.index("unit")] for batch in batches for row in batch.rows
    }
    assert units["dissolved_oxygen"] == "mg/L"
    assert units["salinity"] == "psu"


def test_parse_long_csv_without_a_unit_column_uses_the_default(testdata_path: Path) -> None:
    probe = probe_parse(
        _open(testdata_path, "long_observations.csv"),
        filename="long_observations.csv",
        content_type="text/csv",
    )
    columns = [item for item in probe.proposed_mapping.columns if item.role is not ColumnRole.UNIT]
    mapping = ColumnMapping.model_validate(
        {
            **probe.proposed_mapping.model_dump(),
            "columns": [item.model_dump() for item in columns],
            "default_unit": "mg/L",
        }
    )
    session = ParseSession(
        _open(testdata_path, "long_observations.csv"),
        filename="long_observations.csv",
        content_type=None,
        mapping=mapping,
    )
    batches = list(session)
    unit_index = LONG_SCHEMA_FIELDS.index("unit")
    missing_index = LONG_SCHEMA_FIELDS.index("value")
    units = [
        (row[unit_index], batch.missing[index][unit_index])
        for batch in batches
        for index, row in enumerate(batch.rows)
    ]
    assert all(unit == "mg/L" for unit, _ in units)
    assert all(flag is False for _, flag in units)
    assert missing_index == 3


def test_parse_transcodes_non_utf8_files(testdata_path: Path) -> None:
    probe = probe_parse(_open(testdata_path, "cp1252_non_utf8.csv"), filename="cp1252_non_utf8.csv")
    assert probe.sniff.encoding == "cp1252"
    mapping = _complete_long(probe, default_parameter="temperature")
    session = ParseSession(
        _open(testdata_path, "cp1252_non_utf8.csv"),
        filename="cp1252_non_utf8.csv",
        content_type=None,
        mapping=mapping,
    )
    batches = list(session)
    rows = [row for batch in batches for row in batch.rows]
    assert rows[0] == (
        "St. A",
        "2024-01-15T09:30:00Z",
        "temperature",
        "21.4",
        "°C",
        "",
        "",
        "",
        "",
        "",
        "2",
        "",
    )
    assert rows[1] == (
        "St. B",
        "2024-01-15T10:05:00Z",
        "phosphat",
        "0.03",
        "µg/l",
        "",
        "",
        "",
        "",
        "",
        "3",
        "",
    )


def test_parse_reports_a_ragged_table_without_leaking_content(testdata_path: Path) -> None:
    probe = probe_parse(
        _open(testdata_path, "malformed_ragged.csv"), filename="malformed_ragged.csv"
    )
    mapping = _complete_long(probe, default_unit="mg/L")
    session = ParseSession(
        _open(testdata_path, "malformed_ragged.csv"),
        filename="malformed_ragged.csv",
        content_type=None,
        mapping=mapping,
    )
    with pytest.raises(ParsingError) as error:
        list(session)
    assert "extra_field" not in str(error.value)
    report = session.report
    assert report.completed is False
    assert report.failure is not None
    assert report.failure.code == "parsing_error"
    assert report.failure.details["reason"] == "inconsistent_field_count"


def test_parse_wide_csv_converts_to_long_records(testdata_path: Path) -> None:
    probe = probe_parse(
        _open(testdata_path, "wide_station_matrix.csv"),
        filename="wide_station_matrix.csv",
        content_type="text/csv",
    )
    assert probe.layout is LayoutKind.WIDE
    assert probe.proposed_mapping.wide_axis == "stations"
    columns = [
        item.model_copy(update={"station_label": item.column, "parameter_label": None})
        if item.role is ColumnRole.VALUE
        else item
        for item in probe.proposed_mapping.columns
    ]
    mapping = ColumnMapping.model_validate(
        {
            **probe.proposed_mapping.model_dump(),
            "columns": [item.model_dump() for item in columns],
            "default_parameter": "salinity",
            "default_unit": "psu",
        }
    )
    session = ParseSession(
        _open(testdata_path, "wide_station_matrix.csv"),
        filename="wide_station_matrix.csv",
        content_type=None,
        mapping=mapping,
        batch_rows=7,
    )
    batches = list(session)
    report = session.report

    assert report.wide_records_emitted == 12
    assert report.wide_source_rows_seen == 4
    assert report.wide_source_rows_skipped == 0
    assert count_rows(batches) == 12
    rows = [row for batch in batches for row in batch.rows]
    assert rows[0] == (
        "Outer Channel",
        "2024-01-15",
        "salinity",
        "12,4",
        "psu",
        "",
        "",
        "",
        "",
        "",
        "2",
        "",
    )
    assert rows[11] == (
        "Northern Sector",
        "2024-04-14",
        "salinity",
        "6,2",
        "psu",
        "",
        "",
        "",
        "",
        "",
        "5",
        "",
    )
    assert report.mapping_warnings == ()


def test_parse_parquet_with_declared_fields_and_the_parameter_axis(
    testdata_path: Path,
) -> None:
    probe = probe_parse(
        _open(testdata_path, "observations.parquet"), filename="observations.parquet"
    )
    columns = [
        item.model_copy(update={"parameter_label": item.column, "station_label": None})
        if item.role is ColumnRole.VALUE
        else item
        for item in probe.proposed_mapping.columns
    ]
    columns = [
        item.model_copy(update={"role": ColumnRole.STATION}) if item.column == "station" else item
        for item in columns
    ]
    mapping = ColumnMapping.model_validate(
        {
            **probe.proposed_mapping.model_dump(),
            "columns": [item.model_dump() for item in columns],
            "wide_axis": "parameters",
            "default_unit": "mixed",
        }
    )
    session = ParseSession(
        _open(testdata_path, "observations.parquet"),
        filename="observations.parquet",
        content_type=None,
        mapping=mapping,
    )
    batches = list(session)
    report = session.report

    assert report.row_count == 9
    assert report.wide_records_emitted == 9
    assert report.completed is True
    assert report.skipped_leading_rows == 0
    rows = [row for batch in batches for row in batch.rows]
    assert rows[0] == (
        "St. A",
        "2024-01-15T09:30:00+00:00",
        "sample_count",
        "3",
        "mixed",
        "",
        "",
        "",
        "",
        "",
        "1",
        "",
    )
    salinity_rows = [row for row in rows if row[2] == "salinity"]
    assert [row[3] for row in salinity_rows] == ["12.40", "9.80", "7.25"]
    non_finite = [row for row in rows if row[3] == "nan"]
    assert non_finite[0][0] == "St. C"


def test_parse_workbook_rejects_a_formula_in_a_mapped_column(testdata_path: Path) -> None:
    probe = probe_parse(_open(testdata_path, "observations.xlsx"), filename="observations.xlsx")
    mapping = _complete_long(probe, default_parameter="computed_observation", default_unit="count")
    mapping = _rerole(mapping, "value", ColumnRole.IGNORED)
    mapping = _rerole(mapping, "computed_total", ColumnRole.VALUE)
    session = ParseSession(
        _open(testdata_path, "observations.xlsx"),
        filename="observations.xlsx",
        content_type=None,
        mapping=mapping,
    )
    with pytest.raises(ParsingError) as error:
        list(session)
    assert error.value.details["reason"] == "formula_cell"
    report = session.report
    assert report.failure is not None
    assert report.failure.code == "parsing_error"
    assert report.completed is False


def test_parse_workbook_tolerates_formulas_in_ignored_columns(testdata_path: Path) -> None:
    probe = probe_parse(
        _open(testdata_path, "formulas_cached.xlsx"), filename="formulas_cached.xlsx"
    )
    mapping = _complete_long(probe, default_parameter="computed_observation", default_unit="count")
    session = ParseSession(
        _open(testdata_path, "formulas_cached.xlsx"),
        filename="formulas_cached.xlsx",
        content_type=None,
        mapping=mapping,
        accept_cached_formula_values=True,
    )
    batches = list(session)
    report = session.report

    assert report.completed is True
    assert report.formula_policy == "accept_cached"
    assert report.formula_cells_seen == 2
    assert report.formula_cells_used == 1
    assert report.error_cells_seen == 0
    assert report.sheet == "Observations"
    rows = [row for batch in batches for row in batch.rows]
    assert len(rows) == 3
    assert rows[0][3] == "6.8"
    assert rows[0][LONG_SCHEMA_FIELDS.index("parameter")] == "computed_observation"
    formula_issues = [
        issue
        for issue in report.cell_issues
        if issue.kind in {"formula", "formula_without_cached_value"}
    ]
    assert [(issue.row, issue.column_name) for issue in formula_issues] == [
        (2, "computed_total"),
        (3, "computed_total"),
    ]
    used = [
        issue
        for issue in formula_issues
        if issue.detail == "the cached value of the formula was used"
    ]
    assert len(used) == 1


def test_parse_workbook_rejects_error_cells_in_mapped_columns(testdata_path: Path) -> None:
    probe = probe_parse(_open(testdata_path, "error_cells.xlsx"), filename="error_cells.xlsx")
    mapping = _complete_long(probe, default_parameter="computed_observation", default_unit="count")
    session = ParseSession(
        _open(testdata_path, "error_cells.xlsx"),
        filename="error_cells.xlsx",
        content_type=None,
        mapping=mapping,
    )
    with pytest.raises(ParsingError) as error:
        list(session)
    assert error.value.details["reason"] == "error_cell"
    assert error.value.details["error_code"] == "#DIV/0!"
    report = session.report
    assert report.error_cells_seen == 1


def test_parse_selects_a_named_sheet(testdata_path: Path) -> None:
    """The named sheet is probed and selected before any mapping validation.

    The Notes sheet is a single text column with no timestamp, so no valid long
    mapping exists for it. The parse therefore fails at mapping validation,
    and the failure report proves the requested sheet was the one inspected.
    """
    probe = probe_parse(
        _open(testdata_path, "observations.xlsx"),
        filename="observations.xlsx",
        sheet="Notes",
    )
    assert probe.fields == ("Generated deterministically for the ingestion reader tests.",)
    assert probe.sniff.has_header is True

    columns = [
        MappedColumn(column=probe.fields[0], role=ColumnRole.IGNORED),
    ]
    mapping = ColumnMapping.model_validate(
        {
            "layout": LayoutKind.LONG,
            "columns": [item.model_dump() for item in columns],
            "default_parameter": "note",
            "default_unit": "count",
        }
    )
    session = ParseSession(
        _open(testdata_path, "observations.xlsx"),
        filename="observations.xlsx",
        content_type=None,
        mapping=mapping,
        sheet="Notes",
    )
    with pytest.raises(ValidationError):
        list(session)
    report = session.report
    assert report.completed is False
    assert report.failure is not None
    assert report.failure.code == "validation_error"


def test_parse_session_is_single_use(testdata_path: Path) -> None:
    probe = probe_parse(
        _open(testdata_path, "long_observations.csv"), filename="long_observations.csv"
    )
    mapping = _complete_long(probe)
    session = ParseSession(
        _open(testdata_path, "long_observations.csv"),
        filename="long_observations.csv",
        content_type=None,
        mapping=mapping,
    )
    first = list(session)
    assert first
    with pytest.raises(ParsingError) as error:
        list(session)
    assert "once" in str(error.value)


def test_report_before_the_session_started_is_an_error(testdata_path: Path) -> None:
    probe = probe_parse(
        _open(testdata_path, "long_observations.csv"), filename="long_observations.csv"
    )
    mapping = _complete_long(probe)
    session = ParseSession(
        _open(testdata_path, "long_observations.csv"),
        filename="long_observations.csv",
        content_type=None,
        mapping=mapping,
    )
    with pytest.raises(ParsingError):
        _ = session.report


def test_a_mapping_that_does_not_match_still_produces_a_report(
    testdata_path: Path,
) -> None:
    probe = probe_parse(
        _open(testdata_path, "long_observations.csv"), filename="long_observations.csv"
    )
    mapping = _complete_long(probe)
    stale = mapping.model_copy(
        update={
            "columns": tuple(
                MappedColumn(column=f"old_{item.column}", role=item.role)
                for item in mapping.columns
            )
        }
    )
    session = ParseSession(
        _open(testdata_path, "long_observations.csv"),
        filename="long_observations.csv",
        content_type=None,
        mapping=stale,
    )
    with pytest.raises(ValidationError):
        list(session)
    report = session.report
    assert report.completed is False
    assert report.failure is not None
    assert report.failure.code == "validation_error"
    assert report.file_format == "unknown"


def test_report_round_trips_through_json(testdata_path: Path) -> None:
    from trendsmapp.ingestion.parser import ParseReport

    probe = probe_parse(
        _open(testdata_path, "long_observations.csv"), filename="long_observations.csv"
    )
    mapping = _complete_long(probe)
    session = ParseSession(
        _open(testdata_path, "long_observations.csv"),
        filename="long_observations.csv",
        content_type=None,
        mapping=mapping,
    )
    list(session)
    report = session.report
    restored = ParseReport.model_validate_json(report.model_dump_json())
    assert restored == report
