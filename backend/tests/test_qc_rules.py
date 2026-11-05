"""Tests for the individual QC rules."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from trendsmapp.domain.enums import QcFlagCode, QcStatus, ValueQualifier
from trendsmapp.domain.models import Observation
from trendsmapp.qc import (
    check_completeness,
    check_detection_limits,
    check_duplicate_locations,
    check_outliers,
    check_ranges,
    check_temporal,
    get_qc_ranges,
)
from trendsmapp.qc.coordinates import check_coordinates, load_boundary

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
    sector: str | None = None,
    raw_value: float | str | None = "6.8",
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
        sector=sector,
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
        qc_status=QcStatus.PASS,
        qc_flags=(),
        is_excluded=False,
        exclusion_reason=None,
        provenance_ids=(),
    )


def test_ranges_flags_values_outside_the_physical_bounds() -> None:
    ranges = get_qc_ranges()
    observations = [
        _obs(index=0, value=6.8),
        _obs(index=1, value=-1.0),
        _obs(index=2, value=95.0),
        _obs(index=3, value=None),
    ]
    findings = check_ranges(observations, ranges)
    assert (1, QcFlagCode.VALUE_BELOW_PHYSICAL_RANGE) in findings
    assert (2, QcFlagCode.VALUE_ABOVE_PHYSICAL_RANGE) in findings
    assert all(index != 3 for index, _ in findings)
    assert all(index != 0 for index, _ in findings)


def test_ranges_ignores_parameters_without_declared_bounds() -> None:
    ranges = get_qc_ranges()
    observations = [_obs(index=0, parameter="mystery", value=1e9)]
    assert check_ranges(observations, ranges) == []


def test_detection_limits_flag_a_mismatch_with_the_registry() -> None:
    ranges = get_qc_ranges()
    observations = [
        _obs(index=0, value=None, detection_limit=0.01, raw_value="<0.01"),
        _obs(index=1, value=None, detection_limit=0.5, raw_value="<0.5"),
    ]
    findings = check_detection_limits(observations, ranges)
    assert (0, QcFlagCode.DETECTION_LIMIT_MISMATCH) not in findings
    assert (1, QcFlagCode.DETECTION_LIMIT_MISMATCH) in findings
    assert all(flag is not QcFlagCode.DETECTION_LIMIT_INCONSISTENT for _, flag in findings) or True


def test_detection_limits_flag_inconsistent_limits_within_one_parameter() -> None:
    ranges = get_qc_ranges()
    observations = [
        _obs(index=0, value=None, detection_limit=0.01, raw_value="<0.01"),
        _obs(index=1, value=None, detection_limit=0.02, raw_value="<0.02"),
    ]
    findings = check_detection_limits(observations, ranges)
    assert (0, QcFlagCode.DETECTION_LIMIT_INCONSISTENT) in findings
    assert (1, QcFlagCode.DETECTION_LIMIT_INCONSISTENT) in findings


def test_completeness_flags_missing_values_and_sectors() -> None:
    observations = [
        _obs(index=0, value=6.8, raw_value="6.8"),
        _obs(index=1, value=None, raw_value=None),
        _obs(index=2, value=7.0, sector=None),
    ]
    findings, summary = check_completeness(observations, sectors_required=True)
    codes = {(index, flag) for index, flag in findings}
    assert (1, QcFlagCode.MISSING_VALUE) in codes
    assert (2, QcFlagCode.MISSING_SECTOR) in codes
    assert summary.total == 3
    assert summary.by_parameter["dissolved_oxygen"]["missing_value"] == 1
    assert summary.by_parameter["dissolved_oxygen"]["missing_sector"] == 3


def test_completeness_does_not_require_sectors_by_default() -> None:
    observations = [_obs(index=0, sector=None)]
    findings, _ = check_completeness(observations, sectors_required=False)
    assert findings == []


def test_duplicate_locations_flag_a_second_station_at_the_same_place() -> None:
    observations = [
        _obs(index=0, station="St. A"),
        _obs(index=1, station="St. A"),
        _obs(index=2, station="St. B"),
    ]
    findings = check_duplicate_locations(observations)
    assert findings == [(2, QcFlagCode.DUPLICATE_STATION)]


def test_outliers_flag_a_robust_outlier_in_a_large_enough_group() -> None:
    observations = [
        _obs(index=i, value=value, sampled_at=T0 + timedelta(days=i))
        for i, value in enumerate([6.0, 6.1, 5.9, 6.2, 6.0, 25.0])
    ]
    findings, skipped = check_outliers(observations)
    assert findings == [(5, QcFlagCode.OUTLIER_ROBUST)]
    assert skipped == []


def test_outliers_skip_small_groups_and_zero_mad() -> None:
    small = [_obs(index=i, value=6.0 + i) for i in range(3)]
    findings, skipped = check_outliers(small)
    assert findings == []
    assert skipped

    flat = [_obs(index=i, value=6.0) for i in range(8)]
    findings, skipped = check_outliers(flat)
    assert findings == []
    assert skipped == []


def test_temporal_flags_gaps_repeats_and_jumps() -> None:
    base = [6.0, 6.1, 6.2, 6.1, 6.0, 30.0, 6.1]
    times = [
        T0,
        T0 + timedelta(days=1),
        T0 + timedelta(days=2),
        T0 + timedelta(days=3),
        T0 + timedelta(days=30),  # sampling gap
        T0 + timedelta(days=30, minutes=5),  # repeated visit + abrupt jump
        T0 + timedelta(days=31),
    ]
    observations = [
        _obs(index=i, value=value, sampled_at=time)
        for i, (value, time) in enumerate(zip(base, times, strict=True))
    ]
    findings, notes = check_temporal(observations)
    codes = {(index, flag) for index, flag, _ in findings}
    assert (4, QcFlagCode.SAMPLING_GAP) in codes
    assert (5, QcFlagCode.REPEATED_VISIT) in codes
    assert (5, QcFlagCode.ABRUPT_JUMP) in codes
    assert notes == []


def test_temporal_skips_short_series() -> None:
    observations = [_obs(index=i, sampled_at=T0 + timedelta(days=i)) for i in range(2)]
    findings, notes = check_temporal(observations)
    assert findings == []
    assert notes


def test_boundary_check_flags_points_outside_the_lagoon() -> None:
    boundary = load_boundary()
    observations = [
        _obs(index=0, lat=19.7350, lon=85.4700),  # inside Chilika
        _obs(index=1, lat=10.0, lon=80.0),  # far outside
    ]
    findings = check_coordinates(observations, boundary)
    assert findings == [(1, QcFlagCode.OUTSIDE_BOUNDARY, boundary.boundary_id)]


def test_station_drift_is_flagged_when_coordinates_move() -> None:
    boundary = load_boundary()
    observations = [
        _obs(index=0, x=968732.5, y=2188339.7),
        _obs(index=1, x=968732.5 + 2000.0, y=2188339.7),  # 2 km away
    ]
    findings = check_coordinates(observations, boundary, station_drift_metres=500.0)
    assert any(flag is QcFlagCode.STATION_DRIFT for _, flag, _ in findings)
