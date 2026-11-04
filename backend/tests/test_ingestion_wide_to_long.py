"""Tests for the deterministic wide-to-long conversion."""

from __future__ import annotations

import pytest

from trendsmapp.domain.enums import ColumnRole, LayoutKind
from trendsmapp.errors import ValidationError
from trendsmapp.ingestion.chunking import TextBatch, count_rows
from trendsmapp.ingestion.column_mapping import (
    ColumnMapping,
    MappedColumn,
    resolve_mapping,
)
from trendsmapp.ingestion.wide_to_long import (
    LONG_SCHEMA_FIELDS,
    WideToLongIterator,
    long_schema_columns,
)

WIDE_FIELDS = ("date", "St. A", "St. B", "notes")


def wide_mapping(**overrides: object) -> ColumnMapping:
    """Return a valid station-axis wide mapping."""
    columns = [
        MappedColumn(column="date", role=ColumnRole.TIMESTAMP),
        MappedColumn(column="St. A", role=ColumnRole.VALUE, station_label="St. A"),
        MappedColumn(column="St. B", role=ColumnRole.VALUE, station_label="St. B"),
        MappedColumn(column="notes", role=ColumnRole.IGNORED),
    ]
    data: dict[str, object] = {
        "layout": LayoutKind.WIDE,
        "wide_axis": "stations",
        "columns": columns,
        "default_parameter": "salinity",
    }
    data.update(overrides)
    return ColumnMapping.model_validate(data)


def wide_batch() -> TextBatch:
    """Return one wide batch of data rows.

    The parser's reader consumes the header row before the converter runs, so
    a converter batch contains data rows only; with ``has_header=True`` the
    first data row is physical row two.
    """
    return TextBatch(
        columns=WIDE_FIELDS,
        rows=(
            ("2024-01-15", "12,4", "9,8", "calm"),
            ("2024-02-12", "14,2", "", "windy"),
        ),
        missing=(
            (False, False, False, False),
            (False, False, True, False),
        ),
        first_row_index=0,
    )


def resolved_wide(*, has_header: bool = True, **overrides: object) -> object:
    mapping = wide_mapping(**overrides)
    return resolve_mapping(mapping, fields=WIDE_FIELDS, has_header=has_header)


def test_long_schema_columns_are_stable() -> None:
    assert long_schema_columns() == LONG_SCHEMA_FIELDS
    assert LONG_SCHEMA_FIELDS == (
        "station",
        "sampled_at",
        "parameter",
        "value",
        "unit",
        "qualifier",
        "latitude",
        "longitude",
        "depth_m",
        "sector",
        "source_row",
        "source_sheet",
    )


def test_conversion_resolves_station_labels_from_the_mapping() -> None:
    resolved = resolved_wide()
    iterator = WideToLongIterator(
        batches=iter([wide_batch()]),
        resolved=resolved,  # type: ignore[arg-type]
        source_sheet="",
        batch_rows=10,
    )
    batches = list(iterator)
    assert count_rows(batches) == 4
    rows = [row for batch in batches for row in batch.rows]
    assert rows[0] == ("St. A", "2024-01-15", "salinity", "12,4", "", "", "", "", "", "", "2", "")
    assert rows[1] == ("St. B", "2024-01-15", "salinity", "9,8", "", "", "", "", "", "", "2", "")
    assert rows[2] == ("St. A", "2024-02-12", "salinity", "14,2", "", "", "", "", "", "", "3", "")
    assert rows[3] == ("St. B", "2024-02-12", "salinity", "", "", "", "", "", "", "", "3", "")


def test_conversion_marks_missing_cells_and_ignored_roles() -> None:
    resolved = resolved_wide()
    iterator = WideToLongIterator(
        batches=iter([wide_batch()]),
        resolved=resolved,  # type: ignore[arg-type]
        source_sheet="",
        batch_rows=10,
    )
    batches = list(iterator)

    value_index = LONG_SCHEMA_FIELDS.index("value")
    missing_values = [
        batch.missing[index][value_index]
        for batch in batches
        for index in range(batch.row_count)
    ]
    assert missing_values == [False, False, False, True]

    always_missing = {
        LONG_SCHEMA_FIELDS.index(name)
        for name in ("unit", "qualifier", "latitude", "longitude", "depth_m", "sector")
    }
    for batch in batches:
        for index in range(batch.row_count):
            for field_index in always_missing:
                assert batch.missing[index][field_index] is True

    third_row = batches[0].rows[3]
    third_missing = batches[0].missing[3]
    assert third_row[3] == ""
    assert third_missing[3] is True


def test_conversion_carries_the_source_sheet_and_physical_rows() -> None:
    resolved = resolved_wide()
    iterator = WideToLongIterator(
        batches=iter([wide_batch()]),
        resolved=resolved,  # type: ignore[arg-type]
        source_sheet="Observations",
        batch_rows=10,
    )
    batches = list(iterator)
    rows = [row for batch in batches for row in batch.rows]
    assert all(row[LONG_SCHEMA_FIELDS.index("source_sheet")] == "Observations" for row in rows)
    assert [row[LONG_SCHEMA_FIELDS.index("source_row")] for row in rows] == ["2", "2", "3", "3"]


def test_conversion_skips_rows_without_time_and_values() -> None:
    batch = TextBatch(
        columns=WIDE_FIELDS,
        rows=(
            ("", "", "", "only a note"),
            ("2024-01-15", "12,4", "9,8", ""),
        ),
        missing=(
            (True, True, True, False),
            (False, False, False, True),
        ),
        first_row_index=0,
    )
    resolved = resolved_wide()
    iterator = WideToLongIterator(
        batches=iter([batch]),
        resolved=resolved,  # type: ignore[arg-type]
        source_sheet="",
        batch_rows=10,
    )
    batches = list(iterator)
    assert count_rows(batches) == 2
    assert iterator.stats.source_rows_seen == 2
    assert iterator.stats.source_rows_skipped == 1
    assert iterator.stats.records_emitted == 2


def test_conversion_buffers_records_across_source_batches() -> None:
    first = TextBatch(
        columns=WIDE_FIELDS,
        rows=(("2024-01-15", "1", "2", ""),),
        missing=((False, False, False, True),),
        first_row_index=0,
    )
    second = TextBatch(
        columns=WIDE_FIELDS,
        rows=(("2024-02-12", "3", "4", ""), ("2024-03-10", "5", "6", "")),
        missing=((False, False, False, True), (False, False, False, True)),
        first_row_index=1,
    )
    resolved = resolved_wide()
    iterator = WideToLongIterator(
        batches=iter([first, second]),
        resolved=resolved,  # type: ignore[arg-type]
        source_sheet="",
        batch_rows=3,
    )
    batches = list(iterator)
    assert [batch.row_count for batch in batches] == [3, 3]
    assert [batch.first_row_index for batch in batches] == [0, 3]
    assert count_rows(batches) == 6
    assert iterator.stats.records_emitted == 6


def test_conversion_supports_the_parameter_axis_with_a_station_column() -> None:
    fields = ("date", "station", "salinity", "temperature")
    mapping = ColumnMapping.model_validate(
        {
            "layout": LayoutKind.WIDE,
            "wide_axis": "parameters",
            "columns": [
                MappedColumn(column="date", role=ColumnRole.TIMESTAMP),
                MappedColumn(column="station", role=ColumnRole.STATION),
                MappedColumn(column="salinity", role=ColumnRole.VALUE, parameter_label="salinity"),
                MappedColumn(
                    column="temperature", role=ColumnRole.VALUE, parameter_label="temperature"
                ),
            ],
        }
    )
    resolved = resolve_mapping(mapping, fields=fields, has_header=False)
    batch = TextBatch(
        columns=fields,
        rows=(("2024-01-15", "St. A", "12,4", "21,5"),),
        missing=((False, False, False, False),),
        first_row_index=0,
    )
    iterator = WideToLongIterator(
        batches=iter([batch]),
        resolved=resolved,  # type: ignore[arg-type]
        source_sheet="",
        batch_rows=10,
    )
    batches = list(iterator)
    rows = [row for batch in batches for row in batch.rows]
    assert rows[0] == (
        "St. A",
        "2024-01-15",
        "salinity",
        "12,4",
        "",
        "",
        "",
        "",
        "",
        "",
        "1",
        "",
    )
    assert rows[1][LONG_SCHEMA_FIELDS.index("parameter")] == "temperature"


def test_conversion_requires_a_timestamp_column() -> None:
    mapping = wide_mapping()
    broken = mapping.model_copy(
        update={
            "columns": tuple(
                item for item in mapping.columns if item.role is not ColumnRole.TIMESTAMP
            )
        }
    )
    resolved = resolve_mapping(broken, fields=WIDE_FIELDS, has_header=True)
    iterator = WideToLongIterator(
        batches=iter([wide_batch()]),
        resolved=resolved,  # type: ignore[arg-type]
        source_sheet="",
        batch_rows=10,
    )
    with pytest.raises(ValueError, match="timestamp") as error:
        list(iterator)
    assert "timestamp" in str(error.value)


def test_conversion_uses_the_default_unit_and_parameter() -> None:
    mapping = wide_mapping(default_parameter="salinity", default_unit="psu")
    columns = [
        item if item.role is not ColumnRole.VALUE else item.model_copy(update={"unit": None})
        for item in mapping.columns
    ]
    mapping = mapping.model_copy(update={"columns": tuple(columns)})
    resolved = resolve_mapping(mapping, fields=WIDE_FIELDS, has_header=True)
    iterator = WideToLongIterator(
        batches=iter([wide_batch()]),
        resolved=resolved,  # type: ignore[arg-type]
        source_sheet="",
        batch_rows=10,
    )
    batches = list(iterator)
    rows = [row for batch in batches for row in batch.rows]
    value_index = LONG_SCHEMA_FIELDS.index("value")
    unit_index = LONG_SCHEMA_FIELDS.index("unit")
    parameter_index = LONG_SCHEMA_FIELDS.index("parameter")
    assert all(row[unit_index] == "psu" for row in rows)
    assert all(row[parameter_index] == "salinity" for row in rows)
    assert rows[3][value_index] == ""


def test_conversion_output_always_carries_the_long_schema() -> None:
    resolved = resolved_wide()
    iterator = WideToLongIterator(
        batches=iter([wide_batch()]),
        resolved=resolved,  # type: ignore[arg-type]
        source_sheet="",
        batch_rows=2,
    )
    for batch in iterator:
        assert batch.columns == LONG_SCHEMA_FIELDS


def test_text_batch_rejects_a_bad_missingness_shape_in_the_converter_path() -> None:
    with pytest.raises(ValidationError):
        TextBatch(
            columns=WIDE_FIELDS,
            rows=(("date", "a", "b", "c"),),
            missing=((False, False, False),),
            first_row_index=0,
        )
