"""Tests for canonicalizing long rows into canonical observations."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from pathlib import Path

import pytest

from trendsmapp.domain.enums import ColumnRole, LayoutKind, QcFlagCode, QcStatus, ValueQualifier
from trendsmapp.ingestion import ColumnMapping, MappedColumn, ParseSession, probe_parse
from trendsmapp.ingestion.sniffing import DecimalStyle
from trendsmapp.ingestion.wide_to_long import LONG_SCHEMA_FIELDS
from trendsmapp.normalization.canonicalize import (
    NormalizedRow,
    canonicalize_row,
    derive_station_key,
    observation_id_for,
)
from trendsmapp.normalization.coordinates import normalize_wgs84

DATASET_ID = "ds_" + "a" * 32
DATASET_VERSION_ID = "dsv_" + "b" * 32


def _long_mapping() -> ColumnMapping:
    columns = [
        MappedColumn(column="station", role=ColumnRole.STATION),
        MappedColumn(column="latitude", role=ColumnRole.LATITUDE),
        MappedColumn(column="longitude", role=ColumnRole.LONGITUDE),
        MappedColumn(column="sampled_at", role=ColumnRole.TIMESTAMP),
        MappedColumn(column="parameter", role=ColumnRole.PARAMETER),
        MappedColumn(column="value", role=ColumnRole.VALUE),
        MappedColumn(column="unit", role=ColumnRole.UNIT),
        MappedColumn(column="qualifier", role=ColumnRole.QUALIFIER),
        MappedColumn(column="depth_m", role=ColumnRole.DEPTH),
        MappedColumn(column="notes", role=ColumnRole.IGNORED),
    ]
    return ColumnMapping.model_validate(
        {"layout": LayoutKind.LONG, "columns": [c.model_dump() for c in columns]}
    )


def _parse_long(testdata_path: Path) -> tuple[list, ColumnMapping]:
    payload = testdata_path("long_observations.csv").read_bytes()
    probe = probe_parse(
        io.BytesIO(payload), filename="long_observations.csv", content_type="text/csv"
    )
    mapping = ColumnMapping.model_validate(probe.proposed_mapping.model_dump())
    session = ParseSession(
        io.BytesIO(payload),
        filename="long_observations.csv",
        content_type="text/csv",
        mapping=mapping,
    )
    return list(session), mapping


def _rows(batches: list) -> list[NormalizedRow]:
    return [row for batch in batches for row in NormalizedRow.from_batch(batch)]


def test_canonicalize_builds_observations_with_raw_and_canonical_side_by_side(
    testdata_path: Path,
) -> None:
    batches, mapping = _parse_long(testdata_path)
    rows = _rows(batches)
    results = [
        canonicalize_row(
            row,
            mapping=mapping,
            dataset_id=DATASET_ID,
            dataset_version_id=DATASET_VERSION_ID,
            decimal_style=DecimalStyle.POINT,
        )
        for row in rows
    ]
    assert all(result.observation is not None for result in results)
    assert all(result.skipped is None for result in results)

    first = results[0].observation
    assert first is not None
    assert first.dataset_id == DATASET_ID
    assert first.dataset_version_id == DATASET_VERSION_ID
    assert first.source_row == 2
    assert first.station_label == "St. A"
    assert first.parameter_id == "dissolved_oxygen"
    assert first.sampled_at == datetime(2024, 1, 15, 9, 30, tzinfo=UTC)
    assert first.raw_value == "6.8"
    assert first.raw_unit == "mg/L"
    assert first.canonical_value == pytest.approx(6.8)
    assert first.canonical_unit == "mg/L"
    assert first.value_qualifier is ValueQualifier.MEASURED
    assert first.qc_status is QcStatus.PASS
    assert first.latitude_wgs84 == pytest.approx(19.7350)
    assert first.longitude_wgs84 == pytest.approx(85.4700)
    assert first.x_projected_m is not None
    assert first.y_projected_m is not None
    assert first.source_crs == "EPSG:4326"
    assert first.analysis_crs == "EPSG:32644"


def test_canonicalize_preserves_censored_values_as_limits_never_zero(
    testdata_path: Path,
) -> None:
    batches, mapping = _parse_long(testdata_path)
    results = [
        canonicalize_row(
            row,
            mapping=mapping,
            dataset_id=DATASET_ID,
            dataset_version_id=DATASET_VERSION_ID,
            decimal_style=DecimalStyle.POINT,
        )
        for row in _rows(batches)
    ]
    censored = next(
        result.observation
        for result in results
        if result.observation is not None and result.observation.raw_value == "<0.01"
    )
    assert censored is not None
    assert censored.canonical_value is None
    assert censored.detection_limit == pytest.approx(0.01)
    assert censored.canonical_unit == "mg/L"
    assert censored.value_qualifier is ValueQualifier.BELOW_DETECTION_LIMIT
    assert censored.raw_value == "<0.01"


def test_canonicalize_flags_missing_and_non_finite_values_distinctly(
    testdata_path: Path,
) -> None:
    batches, mapping = _parse_long(testdata_path)
    results = [
        canonicalize_row(
            row,
            mapping=mapping,
            dataset_id=DATASET_ID,
            dataset_version_id=DATASET_VERSION_ID,
            decimal_style=DecimalStyle.POINT,
        )
        for row in _rows(batches)
    ]
    by_raw = {
        result.observation.raw_value: result for result in results if result.observation is not None
    }
    missing = by_raw[None]
    assert missing.observation is not None
    assert missing.observation.canonical_value is None
    assert missing.observation.qc_status is QcStatus.WARNING
    assert any(issue.code == QcFlagCode.MISSING_VALUE.value for issue in missing.issues)

    non_finite = by_raw["nan"]
    assert non_finite.observation is not None
    assert non_finite.observation.canonical_value is None
    assert any(issue.code == QcFlagCode.NON_FINITE_VALUE.value for issue in non_finite.issues)
    assert not any(issue.code == QcFlagCode.MISSING_VALUE.value for issue in non_finite.issues)


def test_canonicalize_converts_units_and_records_the_factor(testdata_path: Path) -> None:
    batches, mapping = _parse_long(testdata_path)
    rows = _rows(batches)
    converted = None
    for row in rows:
        result = canonicalize_row(
            row,
            mapping=mapping,
            dataset_id=DATASET_ID,
            dataset_version_id=DATASET_VERSION_ID,
            decimal_style=DecimalStyle.POINT,
        )
        if result.observation is not None and result.observation.raw_unit == "psu":
            converted = result.observation
            break
    assert converted is not None
    assert converted.parameter_id == "salinity"
    assert converted.canonical_value == pytest.approx(12.4)
    assert converted.canonical_unit == "1"
    assert converted.conversion_factor == pytest.approx(1.0)


def test_canonicalize_reports_unknown_parameters_without_dropping_the_row() -> None:
    batch_rows = [
        (
            "St. A",
            "2024-01-15T09:30:00Z",
            "mystery_thing",
            "5",
            "mg/L",
            "",
            "19.7",
            "85.4",
            "",
            "",
            "0.5",
            "",
            "2",
            "",
        )
    ]
    missing = tuple(False for _ in LONG_SCHEMA_FIELDS)
    from trendsmapp.ingestion.chunking import TextBatch

    batch = TextBatch(
        columns=LONG_SCHEMA_FIELDS, rows=tuple(batch_rows), missing=(missing,), first_row_index=0
    )
    row = NormalizedRow.from_batch(batch).__next__()
    result = canonicalize_row(
        row,
        mapping=_long_mapping(),
        dataset_id=DATASET_ID,
        dataset_version_id=DATASET_VERSION_ID,
        decimal_style=DecimalStyle.POINT,
    )
    assert result.observation is not None
    assert result.skipped is None
    assert result.observation.parameter_id == ""
    assert result.observation.parameter_label == "mystery_thing"
    assert result.observation.canonical_value is None
    assert any(issue.code == QcFlagCode.UNKNOWN_PARAMETER.value for issue in result.issues)
    assert result.observation.qc_status is QcStatus.WARNING


def test_canonicalize_skips_rows_without_a_timestamp() -> None:
    from trendsmapp.ingestion.chunking import TextBatch

    row_values = (
        "St. A",
        "",
        "dissolved_oxygen",
        "5",
        "mg/L",
        "",
        "19.7",
        "85.4",
        "",
        "",
        "0.5",
        "",
        "2",
        "",
    )
    missing = tuple(name in {"sampled_at"} for name in LONG_SCHEMA_FIELDS)
    batch = TextBatch(
        columns=LONG_SCHEMA_FIELDS, rows=(row_values,), missing=(missing,), first_row_index=0
    )
    row = NormalizedRow.from_batch(batch).__next__()
    result = canonicalize_row(
        row,
        mapping=_long_mapping(),
        dataset_id=DATASET_ID,
        dataset_version_id=DATASET_VERSION_ID,
        decimal_style=DecimalStyle.POINT,
    )
    assert result.observation is None
    assert result.skipped is not None
    assert result.skipped.reason == "missing_timestamp"


def test_canonicalize_skips_unparsable_timestamps_with_a_coded_reason() -> None:
    from trendsmapp.ingestion.chunking import TextBatch

    row_values = (
        "St. A",
        "not a date",
        "dissolved_oxygen",
        "5",
        "mg/L",
        "",
        "19.7",
        "85.4",
        "",
        "",
        "0.5",
        "",
        "2",
        "",
    )
    missing = tuple(False for _ in LONG_SCHEMA_FIELDS)
    batch = TextBatch(
        columns=LONG_SCHEMA_FIELDS, rows=(row_values,), missing=(missing,), first_row_index=0
    )
    row = NormalizedRow.from_batch(batch).__next__()
    result = canonicalize_row(
        row,
        mapping=_long_mapping(),
        dataset_id=DATASET_ID,
        dataset_version_id=DATASET_VERSION_ID,
        decimal_style=DecimalStyle.POINT,
    )
    assert result.observation is None
    assert result.skipped is not None
    assert result.skipped.reason == QcFlagCode.AMBIGUOUS_TIMESTAMP.value


def test_canonicalize_skips_rows_without_usable_coordinates() -> None:
    from trendsmapp.ingestion.chunking import TextBatch

    row_values = (
        "St. A",
        "2024-01-15T09:30:00Z",
        "dissolved_oxygen",
        "5",
        "mg/L",
        "",
        "",
        "",
        "",
        "",
        "0.5",
        "",
        "2",
        "",
    )
    missing = tuple(name in {"latitude", "longitude"} for name in LONG_SCHEMA_FIELDS)
    batch = TextBatch(
        columns=LONG_SCHEMA_FIELDS, rows=(row_values,), missing=(missing,), first_row_index=0
    )
    row = NormalizedRow.from_batch(batch).__next__()
    result = canonicalize_row(
        row,
        mapping=_long_mapping(),
        dataset_id=DATASET_ID,
        dataset_version_id=DATASET_VERSION_ID,
        decimal_style=DecimalStyle.POINT,
    )
    assert result.observation is None
    assert result.skipped is not None
    assert result.skipped.reason == "missing_coordinate"


def test_canonicalize_uses_station_coordinates_when_the_row_has_none() -> None:
    from trendsmapp.ingestion.chunking import TextBatch

    row_values = (
        "St. A",
        "2024-01-15T09:30:00Z",
        "dissolved_oxygen",
        "5",
        "mg/L",
        "",
        "",
        "",
        "",
        "",
        "0.5",
        "",
        "2",
        "",
    )
    missing = tuple(
        name in {"latitude", "longitude", "easting", "northing"} for name in LONG_SCHEMA_FIELDS
    )
    batch = TextBatch(
        columns=LONG_SCHEMA_FIELDS, rows=(row_values,), missing=(missing,), first_row_index=0
    )
    row = NormalizedRow.from_batch(batch).__next__()
    station_coordinates = {"st_a": normalize_wgs84("19.7350", "85.4700")}
    result = canonicalize_row(
        row,
        mapping=_long_mapping(),
        dataset_id=DATASET_ID,
        dataset_version_id=DATASET_VERSION_ID,
        decimal_style=DecimalStyle.POINT,
        station_coordinates=station_coordinates,
    )
    assert result.observation is not None
    assert result.observation.latitude_wgs84 == pytest.approx(19.7350)


def test_canonicalize_reads_projected_coordinates_with_the_declared_crs() -> None:
    from trendsmapp.ingestion.chunking import TextBatch

    mapping = ColumnMapping.model_validate(
        {
            "layout": LayoutKind.LONG,
            "columns": [
                {"column": "station", "role": "station"},
                {"column": "easting", "role": "easting"},
                {"column": "northing", "role": "northing"},
                {"column": "sampled_at", "role": "timestamp"},
                {"column": "parameter", "role": "parameter"},
                {"column": "value", "role": "value"},
                {"column": "unit", "role": "unit"},
            ],
            "source_crs": "EPSG:32644",
        }
    )
    row_values = (
        "St. A",
        "2024-01-15T09:30:00Z",
        "dissolved_oxygen",
        "5",
        "mg/L",
        "",
        "",
        "",
        "646000",
        "2185000",
        "0.5",
        "",
        "2",
        "",
    )
    missing = tuple(name in {"latitude", "longitude"} for name in LONG_SCHEMA_FIELDS)
    batch = TextBatch(
        columns=LONG_SCHEMA_FIELDS, rows=(row_values,), missing=(missing,), first_row_index=0
    )
    row = NormalizedRow.from_batch(batch).__next__()
    result = canonicalize_row(
        row,
        mapping=mapping,
        dataset_id=DATASET_ID,
        dataset_version_id=DATASET_VERSION_ID,
        decimal_style=DecimalStyle.POINT,
    )
    assert result.observation is not None
    assert result.observation.source_crs == "EPSG:32644"
    assert result.observation.x_projected_m == pytest.approx(646000.0)
    assert -90 <= result.observation.latitude_wgs84 <= 90


def test_observation_ids_are_deterministic() -> None:
    first = observation_id_for(
        dataset_version_id=DATASET_VERSION_ID,
        source_sheet="",
        source_row=2,
        station_key="st_a",
        parameter_id="dissolved_oxygen",
        sampled_at=datetime(2024, 1, 15, 9, 30, tzinfo=UTC),
    )
    second = observation_id_for(
        dataset_version_id=DATASET_VERSION_ID,
        source_sheet="",
        source_row=2,
        station_key="st_a",
        parameter_id="dissolved_oxygen",
        sampled_at=datetime(2024, 1, 15, 9, 30, tzinfo=UTC),
    )
    other = observation_id_for(
        dataset_version_id=DATASET_VERSION_ID,
        source_sheet="",
        source_row=3,
        station_key="st_a",
        parameter_id="dissolved_oxygen",
        sampled_at=datetime(2024, 1, 15, 9, 30, tzinfo=UTC),
    )
    assert first == second
    assert first != other
    assert first.startswith("obs_")


def test_derive_station_key_normalizes_labels() -> None:
    assert derive_station_key("St. A") == derive_station_key("st a")
    assert derive_station_key("St. A") != derive_station_key("St. B")
