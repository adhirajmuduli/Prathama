"""Tests for WGS84 validation and projected-coordinate derivation."""

from __future__ import annotations

import pytest

from trendsmapp.errors import ValidationError
from trendsmapp.normalization.coordinates import (
    CoordinateResult,
    normalize_projected,
    normalize_wgs84,
)


def test_normalize_wgs84_derives_projected_coordinates() -> None:
    result = normalize_wgs84("19.7350", "85.4700")
    assert isinstance(result, CoordinateResult)
    assert result.latitude == pytest.approx(19.7350)
    assert result.longitude == pytest.approx(85.4700)
    assert result.x_projected_m is not None
    assert result.x_projected_m > 0
    assert result.y_projected_m is not None
    assert result.y_projected_m > 0
    assert result.source_crs == "EPSG:4326"
    assert result.analysis_crs == "EPSG:32644"
    assert result.issues == ()


def test_normalize_wgs84_round_trips_through_the_analysis_crs() -> None:
    forward = normalize_wgs84("19.7350", "85.4700")
    back = normalize_projected(
        str(forward.x_projected_m), str(forward.y_projected_m), source_crs=forward.analysis_crs
    )
    assert back.latitude == pytest.approx(19.7350, abs=1e-6)
    assert back.longitude == pytest.approx(85.4700, abs=1e-6)


def test_normalize_wgs84_flags_out_of_range_coordinates_without_projecting() -> None:
    result = normalize_wgs84("95", "85")
    assert result.latitude is None
    assert result.longitude == pytest.approx(85.0)
    assert result.x_projected_m is None
    assert any("coordinate_out_of_range" in issue for issue in result.issues)


def test_normalize_wgs84_flags_non_finite_and_unparsable_values() -> None:
    assert any("non_finite_coordinate" in issue for issue in normalize_wgs84("nan", "85").issues)
    assert any("invalid_coordinate" in issue for issue in normalize_wgs84("abc", "85").issues)
    assert any("missing_coordinate" in issue for issue in normalize_wgs84("", "85").issues)


def test_normalize_projected_derives_wgs84_and_analysis_coordinates() -> None:
    result = normalize_projected("646000", "2185000", source_crs="EPSG:32644")
    assert result.source_crs == "EPSG:32644"
    assert result.x_projected_m == pytest.approx(646000.0)
    assert result.y_projected_m == pytest.approx(2185000.0)
    assert result.latitude is not None
    assert -90 <= result.latitude <= 90
    assert result.longitude is not None
    assert -180 <= result.longitude <= 180
    assert result.issues == ()


def test_normalize_projected_records_the_source_crs() -> None:
    result = normalize_projected("1000", "2000", source_crs="EPSG:32643")
    assert result.source_crs == "EPSG:32643"
    assert result.analysis_crs == "EPSG:32644"
    assert result.x_projected_m != pytest.approx(1000.0)


def test_invalid_crs_is_a_validation_error() -> None:
    with pytest.raises(ValidationError) as error:
        normalize_wgs84("19.7", "85.4", source_crs="not-a-crs")
    assert error.value.details["reason"] == "invalid_crs"


def test_a_custom_analysis_crs_is_used() -> None:
    result = normalize_wgs84("19.7350", "85.4700", analysis_crs="EPSG:32645")
    assert result.analysis_crs == "EPSG:32645"
    assert result.x_projected_m is not None
