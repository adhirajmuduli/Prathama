"""Tests for the normalization pipeline and the canonical Parquet writer."""

from __future__ import annotations

import io
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from trendsmapp.domain.enums import DuplicatePolicy, QcFlagCode
from trendsmapp.ingestion import ColumnMapping, ParseSession, probe_parse
from trendsmapp.ingestion.chunking import TextBatch
from trendsmapp.ingestion.sniffing import DecimalStyle
from trendsmapp.normalization import normalize_wgs84
from trendsmapp.normalization import pipeline as pipeline_module
from trendsmapp.normalization.pipeline import (
    CANONICAL_PARQUET_SCHEMA,
    NormalizationPipeline,
    NormalizationReport,
    write_canonical_parquet,
)

DATASET_ID = "ds_" + "a" * 32
DATASET_VERSION_ID = "dsv_" + "b" * 32


def _long_batches(testdata_path: Path, filename: str = "long_observations.csv"):
    payload = testdata_path(filename).read_bytes()
    probe = probe_parse(io.BytesIO(payload), filename=filename, content_type="text/csv")
    mapping = ColumnMapping.model_validate(probe.proposed_mapping.model_dump())
    session = ParseSession(
        io.BytesIO(payload), filename=filename, content_type="text/csv", mapping=mapping
    )
    return list(session), mapping


def test_pipeline_normalizes_the_long_fixture(testdata_path: Path) -> None:
    batches, mapping = _long_batches(testdata_path)
    pipeline = NormalizationPipeline(
        mapping=mapping,
        dataset_id=DATASET_ID,
        dataset_version_id=DATASET_VERSION_ID,
        decimal_style=DecimalStyle.POINT,
    )
    result = pipeline.run(batches)
    report = result.report

    assert isinstance(report, NormalizationReport)
    assert report.row_count == 12
    assert report.observation_count == 12
    assert report.skipped_count == 0
    assert report.dataset_id == DATASET_ID
    assert report.mapping == mapping
    assert report.issue_counts["missing_value"] == 1
    assert report.issue_counts["non_finite_value"] == 1
    assert report.sorted is True
    assert report.sort_key == ("sampled_at", "station_id", "parameter_id", "source_row")
    assert len(result.observations) == 12
    assert all(
        observation.dataset_version_id == DATASET_VERSION_ID for observation in result.observations
    )


def test_pipeline_flags_duplicate_observations_under_the_declared_policy(
    testdata_path: Path,
) -> None:
    batches, mapping = _long_batches(testdata_path)
    duplicated = batches[0]
    extra_row = duplicated.rows[0]
    extra_missing = duplicated.missing[0]
    batch_with_duplicate = TextBatch(
        columns=duplicated.columns,
        rows=(*duplicated.rows, extra_row),
        missing=(*duplicated.missing, extra_missing),
        first_row_index=duplicated.first_row_index,
    )
    all_batches = [batch_with_duplicate, *batches[1:]]
    pipeline = NormalizationPipeline(
        mapping=mapping,
        dataset_id=DATASET_ID,
        dataset_version_id=DATASET_VERSION_ID,
        decimal_style=DecimalStyle.POINT,
        duplicate_policy=DuplicatePolicy.FLAG_ALL,
    )
    result = pipeline.run(all_batches)
    report = result.report
    assert report.duplicate_groups == 1
    assert report.duplicate_rows_flagged == 1
    flagged = [
        observation
        for observation in result.observations
        if QcFlagCode.DUPLICATE_OBSERVATION in observation.qc_flags
    ]
    assert len(flagged) == 1


def test_pipeline_error_policy_refuses_duplicates(testdata_path: Path) -> None:
    from trendsmapp.errors import ValidationError

    batches, mapping = _long_batches(testdata_path)
    duplicated = batches[0]
    batch_with_duplicate = TextBatch(
        columns=duplicated.columns,
        rows=(*duplicated.rows, duplicated.rows[0]),
        missing=(*duplicated.missing, duplicated.missing[0]),
        first_row_index=duplicated.first_row_index,
    )
    pipeline = NormalizationPipeline(
        mapping=mapping,
        dataset_id=DATASET_ID,
        dataset_version_id=DATASET_VERSION_ID,
        decimal_style=DecimalStyle.POINT,
        duplicate_policy=DuplicatePolicy.ERROR,
    )
    with pytest.raises(ValidationError) as error:
        pipeline.run([batch_with_duplicate, *batches[1:]])
    assert error.value.details["reason"] == "duplicate_observations"


def test_parquet_write_is_deterministic_and_readable(testdata_path: Path) -> None:
    batches, mapping = _long_batches(testdata_path)
    pipeline = NormalizationPipeline(
        mapping=mapping,
        dataset_id=DATASET_ID,
        dataset_version_id=DATASET_VERSION_ID,
        decimal_style=DecimalStyle.POINT,
    )
    result = pipeline.run(batches)

    first_buffer = io.BytesIO()
    second_buffer = io.BytesIO()
    artifact_a = write_canonical_parquet(
        result.observations,
        first_buffer,
        dataset_id=DATASET_ID,
        dataset_version_id=DATASET_VERSION_ID,
    )
    artifact_b = write_canonical_parquet(
        result.observations,
        second_buffer,
        dataset_id=DATASET_ID,
        dataset_version_id=DATASET_VERSION_ID,
    )
    assert artifact_a.sha256 == artifact_b.sha256
    assert artifact_a.row_count == 12
    assert artifact_a.size_bytes == len(first_buffer.getvalue())

    first_buffer.seek(0)
    parquet = pq.ParquetFile(first_buffer)
    assert len(parquet.schema_arrow) == len(CANONICAL_PARQUET_SCHEMA)
    metadata = {
        key.decode(): value.decode() for key, value in (parquet.schema_arrow.metadata or {}).items()
    }
    assert metadata["schema_version"] == "1.0.0"
    assert metadata["application_version"] == "0.1.0"
    assert metadata["dataset_id"] == DATASET_ID
    assert metadata["dataset_version_id"] == DATASET_VERSION_ID
    assert metadata["row_count"] == "12"
    assert metadata["sorted"] == "true"

    table = parquet.read()
    assert table.num_rows == 12
    rows = table.to_pylist()
    sort_positions = [
        (row["sampled_at"], row["station_id"], row["parameter_id"], row["source_row"])
        for row in rows
    ]
    assert sort_positions == sorted(sort_positions)
    censored = next(row for row in rows if row["raw_value"] == "<0.01")
    assert censored["canonical_value"] is None
    assert censored["detection_limit"] == pytest.approx(0.01)
    assert censored["value_qualifier"] == "below_detection_limit"
    assert censored["raw_value"] == "<0.01"
    assert censored["raw_unit"] == "mg/L"


def test_parquet_writer_records_stream_order_above_the_sort_cap(
    testdata_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pipeline_module, "MAX_SORT_IN_MEMORY_ROWS", 5)
    batches, mapping = _long_batches(testdata_path)
    pipeline = NormalizationPipeline(
        mapping=mapping,
        dataset_id=DATASET_ID,
        dataset_version_id=DATASET_VERSION_ID,
        decimal_style=DecimalStyle.POINT,
    )
    result = pipeline.run(batches)
    assert result.report.sorted is False
    assert any("stream order" in warning for warning in result.report.warnings)

    buffer = io.BytesIO()
    artifact = write_canonical_parquet(
        result.observations,
        buffer,
        dataset_id=DATASET_ID,
        dataset_version_id=DATASET_VERSION_ID,
        sorted_rows=False,
    )
    buffer.seek(0)
    metadata = {
        key.decode(): value.decode()
        for key, value in (pq.ParquetFile(buffer).schema_arrow.metadata or {}).items()
    }
    assert metadata["sorted"] == "false"
    assert artifact.row_count == 12


def test_report_round_trips_through_json(testdata_path: Path) -> None:
    batches, mapping = _long_batches(testdata_path)
    pipeline = NormalizationPipeline(
        mapping=mapping,
        dataset_id=DATASET_ID,
        dataset_version_id=DATASET_VERSION_ID,
        decimal_style=DecimalStyle.POINT,
    )
    result = pipeline.run(batches)
    restored = NormalizationReport.model_validate_json(result.report.model_dump_json())
    assert restored == result.report


def test_wide_fixture_normalizes_through_the_pipeline(testdata_path: Path) -> None:
    from trendsmapp.domain.enums import ColumnRole as Role

    payload = testdata_path("wide_station_matrix.csv").read_bytes()
    probe = probe_parse(
        io.BytesIO(payload), filename="wide_station_matrix.csv", content_type="text/csv"
    )
    columns = [
        item.model_copy(update={"station_label": item.column, "parameter_label": None})
        if item.role is Role.VALUE
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
        io.BytesIO(payload), filename="wide_station_matrix.csv", content_type=None, mapping=mapping
    )
    batches = list(session)
    pipeline = NormalizationPipeline(
        mapping=mapping,
        dataset_id=DATASET_ID,
        dataset_version_id=DATASET_VERSION_ID,
        decimal_style=DecimalStyle.COMMA,
        station_coordinates={
            "outer_channel": normalize_wgs84("19.73", "85.47"),
            "central_sector": normalize_wgs84("19.75", "85.49"),
            "northern_sector": normalize_wgs84("19.80", "85.52"),
        },
    )
    result = pipeline.run(batches)
    assert result.report.observation_count == 12
    assert result.report.row_count == 12
    salinity = [o for o in result.observations if o.parameter_id == "salinity"]
    assert len(salinity) == 12
    first = salinity[0]
    assert first.canonical_value == pytest.approx(12.4)
    assert first.canonical_unit == "1"
    assert first.station_label == "Outer Channel"
    assert first.latitude_wgs84 == pytest.approx(19.73)
