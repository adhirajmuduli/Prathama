"""Tests for the boundary resource provenance and the QC pipeline."""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

import trendsmapp.resources as resources_module
from trendsmapp.domain.enums import QcFlagCode, QcStatus, ValueQualifier
from trendsmapp.domain.models import Observation
from trendsmapp.errors import ValidationError
from trendsmapp.ingestion import ColumnMapping, ParseSession, probe_parse
from trendsmapp.ingestion.sniffing import DecimalStyle
from trendsmapp.normalization import NormalizationPipeline
from trendsmapp.qc import QcPipeline, QcReport, load_boundary
from trendsmapp.qc.coordinates import BOUNDARY_GEOJSON

T0 = datetime(2024, 1, 15, 9, 30, tzinfo=UTC)


def _obs(
    *,
    index: int = 0,
    station: str = "St. A",
    lat: float = 19.7350,
    lon: float = 85.4700,
    x: float = 968732.5,
    y: float = 2188339.7,
    parameter: str = "dissolved_oxygen",
    value: float | None = 6.8,
    sampled_at: datetime = T0,
    detection_limit: float | None = None,
    raw_value: float | str | None = "6.8",
    flags: tuple[QcFlagCode, ...] = (),
    status: QcStatus = QcStatus.PASS,
) -> Observation:
    return Observation(
        observation_id=f"obs_{index:032d}",
        dataset_id="ds_test",
        dataset_version_id="dsv_test",
        source_row=index + 2,
        source_sheet=None,
        station_id=f"stn_{station}",
        station_label=station,
        latitude_wgs84=lat,
        longitude_wgs84=lon,
        x_projected_m=x,
        y_projected_m=y,
        source_crs="EPSG:4326",
        analysis_crs="EPSG:32644",
        sector=None,
        sampled_at=sampled_at,
        sampling_depth_m=0.5,
        parameter_id=parameter,
        parameter_label=parameter,
        raw_value=raw_value,
        raw_unit="mg/L",
        value_qualifier=ValueQualifier.MEASURED,
        canonical_value=value,
        canonical_unit="mg/L" if value is not None else None,
        detection_limit=detection_limit,
        method_id=None,
        instrument_id=None,
        qc_status=status,
        qc_flags=flags,
        is_excluded=False,
        exclusion_reason=None,
        provenance_ids=(),
    )


# --- boundary provenance -------------------------------------------------------


def test_boundary_loads_with_verified_provenance() -> None:
    boundary = load_boundary()
    assert boundary.boundary_id == "relation/1917079"
    assert boundary.license == "ODbL 1.0"
    assert "openstreetmap.org" in boundary.attribution
    assert boundary.sha256 == "6a18811f70f56e4f4b3455b6e376470da447483821faeaef93147fc0100b9775"
    assert boundary.contains(85.47, 19.73) is True
    assert boundary.contains(80.0, 10.0) is False


def test_boundary_loader_rejects_a_tampered_geojson(monkeypatch: pytest.MonkeyPatch) -> None:
    import trendsmapp.qc.coordinates as coordinates_module

    real_bytes = resources_module.read_resource_bytes(BOUNDARY_GEOJSON)
    tampered = real_bytes.replace(b"Chilika", b"Tampered")
    monkeypatch.setattr(resources_module, "read_resource_bytes", lambda name: tampered)
    monkeypatch.setattr(coordinates_module, "read_resource_bytes", lambda name: tampered)
    coordinates_module.load_boundary.cache_clear()
    with pytest.raises(ValidationError) as error:
        load_boundary()
    assert "does not match the provenance digest" in str(error.value)
    assert error.value.details["expected"] != error.value.details["actual"]
    coordinates_module.load_boundary.cache_clear()


def test_boundary_loader_rejects_a_missing_sidecar_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        resources_module,
        "load_yaml_resource",
        lambda name: {"schema_version": "1.0.0", "resource": BOUNDARY_GEOJSON},
    )
    import trendsmapp.qc.coordinates as coordinates_module

    monkeypatch.setattr(
        coordinates_module, "load_yaml_resource", resources_module.load_yaml_resource
    )
    coordinates_module.load_boundary.cache_clear()
    with pytest.raises(ValidationError) as error:
        load_boundary()
    assert "sha256" in str(error.value)
    coordinates_module.load_boundary.cache_clear()


def test_boundary_loader_rejects_a_sidecar_for_another_resource(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        resources_module,
        "load_yaml_resource",
        lambda name: {
            "schema_version": "1.0.0",
            "resource": "other.geojson",
            "sha256": "0" * 64,
        },
    )
    import trendsmapp.qc.coordinates as coordinates_module

    monkeypatch.setattr(
        coordinates_module, "load_yaml_resource", resources_module.load_yaml_resource
    )
    coordinates_module.load_boundary.cache_clear()
    with pytest.raises(ValidationError) as error:
        load_boundary()
    assert "points at" in str(error.value)
    coordinates_module.load_boundary.cache_clear()


def test_boundary_loader_rejects_a_multi_feature_geojson(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
                "properties": {"@id": "x"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[2, 2], [3, 2], [3, 3], [2, 2]]]},
                "properties": {"@id": "y"},
            },
        ],
    }
    payload = json.dumps(document).encode()
    monkeypatch.setattr(
        resources_module,
        "load_yaml_resource",
        lambda name: {
            "schema_version": "1.0.0",
            "resource": BOUNDARY_GEOJSON,
            "sha256": __import__("hashlib").sha256(payload).hexdigest(),
            "license": "x",
            "attribution": "x",
            "source": "x",
        },
    )
    import trendsmapp.qc.coordinates as coordinates_module

    monkeypatch.setattr(
        coordinates_module, "load_yaml_resource", resources_module.load_yaml_resource
    )
    monkeypatch.setattr(coordinates_module, "read_resource_bytes", lambda name: payload)
    coordinates_module.load_boundary.cache_clear()
    with pytest.raises(ValidationError) as error:
        load_boundary()
    assert "exactly one feature" in str(error.value)
    coordinates_module.load_boundary.cache_clear()


# --- QC pipeline ----------------------------------------------------------------


def test_pipeline_flags_and_reports_without_deleting(testdata_path: Path) -> None:
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
    batches = list(session)
    norm = NormalizationPipeline(
        mapping=mapping,
        dataset_id="ds_test",
        dataset_version_id="dsv_test",
        decimal_style=DecimalStyle.POINT,
    ).run(batches)

    result = QcPipeline(dataset_id="ds_test", dataset_version_id="dsv_test").run(
        list(norm.observations)
    )
    report = result.report

    assert isinstance(report, QcReport)
    assert report.observation_count == 12
    assert report.boundary_id == "relation/1917079"
    assert "ranges" in report.rules_applied
    assert "temporal" in report.rules_applied
    assert report.flagged_count > 0
    assert report.fail_count >= 1  # the nan salinity row fails as non-finite
    counts = report.flag_counts()
    assert counts.get("missing_value") == 2
    assert counts.get("non_finite_value") == 1
    assert counts.get("abrupt_jump") == 2
    assert len(result.observations) == 12  # nothing was deleted
    flagged = [o for o in result.observations if o.qc_flags]
    assert all(o.qc_status in {QcStatus.WARNING, QcStatus.FAIL} for o in flagged)
    failed = [o for o in result.observations if o.qc_status is QcStatus.FAIL]
    assert all(QcFlagCode.NON_FINITE_VALUE in o.qc_flags for o in failed)


def test_pipeline_status_severity_uses_the_domain_policy() -> None:
    observations = [
        _obs(index=0, value=6.8),
        _obs(
            index=1,
            value=None,
            raw_value="nan",
            flags=(QcFlagCode.NON_FINITE_VALUE,),
            status=QcStatus.FAIL,
        ),
        _obs(
            index=2,
            value=95.0,
            flags=(QcFlagCode.VALUE_ABOVE_PHYSICAL_RANGE,),
            status=QcStatus.WARNING,
        ),
    ]
    result = QcPipeline(
        dataset_id="ds_test", dataset_version_id="dsv_test", use_boundary=False
    ).run(observations)
    report = result.report
    assert report.pass_count >= 1
    assert report.fail_count == 1
    assert report.warning_count == 1
    assert report.rules_skipped == ("boundary_and_drift: no boundary configured",)


def test_pipeline_report_round_trips_through_json(testdata_path: Path) -> None:
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
    norm = NormalizationPipeline(
        mapping=mapping,
        dataset_id="ds_test",
        dataset_version_id="dsv_test",
        decimal_style=DecimalStyle.POINT,
    ).run(list(session))
    result = QcPipeline(dataset_id="ds_test", dataset_version_id="dsv_test").run(
        list(norm.observations)
    )
    restored = QcReport.model_validate_json(result.report.model_dump_json())
    assert restored == result.report
    summary = restored.to_summary_dict()
    assert summary["observation_count"] == 12
    assert summary["flags"]


def test_pipeline_is_deterministic(testdata_path: Path) -> None:
    payload = testdata_path("long_observations.csv").read_bytes()

    def run_once() -> QcReport:
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
        norm = NormalizationPipeline(
            mapping=mapping,
            dataset_id="ds_test",
            dataset_version_id="dsv_test",
            decimal_style=DecimalStyle.POINT,
        ).run(list(session))
        return (
            QcPipeline(dataset_id="ds_test", dataset_version_id="dsv_test")
            .run(list(norm.observations))
            .report
        )

    first = run_once()
    second = run_once()
    assert first == second
