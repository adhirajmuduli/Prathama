"""Tests for temporal alignment, interpolation, seasons, trends, and change points."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from trendsmapp.domain.enums import QcStatus, TemporalInterpolation, ValueQualifier
from trendsmapp.domain.models import Observation
from trendsmapp.errors import ResourceLimitError, ValidationError
from trendsmapp.temporal.alignment import TimeResolution, align_series, bucket_start
from trendsmapp.temporal.change_points import detect_change_points
from trendsmapp.temporal.interpolation import FrameStatus, interpolate_series
from trendsmapp.temporal.pipeline import TemporalRecipe, run_temporal_analysis
from trendsmapp.temporal.seasonal import label_for
from trendsmapp.temporal.trends import theil_sen_trend

T0 = datetime(2024, 1, 15, 9, 30, tzinfo=UTC)


class TestAlignment:
    def test_buckets_and_missing_periods(self) -> None:
        times = [T0, T0 + timedelta(days=1), T0 + timedelta(days=3)]
        result = align_series(times, resolution=TimeResolution.DAY)
        assert result.observed_count == 3
        day0 = bucket_start(T0, TimeResolution.DAY)
        assert result.missing == (day0 + timedelta(days=2),)
        assert result.missing_count == 1

    def test_month_buckets(self) -> None:
        times = [
            datetime(2024, 1, 15, tzinfo=UTC),
            datetime(2024, 3, 2, tzinfo=UTC),
        ]
        result = align_series(times, resolution=TimeResolution.MONTH)
        assert result.observed_count == 2
        assert result.missing == (datetime(2024, 2, 1, tzinfo=UTC),)

    def test_bucket_start(self) -> None:
        moment = datetime(2024, 3, 15, 17, 45, tzinfo=UTC)
        assert bucket_start(moment, TimeResolution.DAY) == datetime(2024, 3, 15, tzinfo=UTC)
        assert bucket_start(moment, TimeResolution.MONTH) == datetime(2024, 3, 1, tzinfo=UTC)
        hour = bucket_start(moment, TimeResolution.HOUR)
        assert (hour.minute, hour.second) == (0, 0)

    def test_empty_series_rejected(self) -> None:
        with pytest.raises(ValidationError):
            align_series([], resolution=TimeResolution.DAY)


class TestInterpolation:
    def test_observed_frames_keep_their_values(self) -> None:
        times = [T0, T0 + timedelta(days=1), T0 + timedelta(days=2)]
        values = [1.0, 2.0, 4.0]
        frames = interpolate_series(times, values, frame_times=times)
        assert all(frame.status is FrameStatus.OBSERVED for frame in frames)
        assert [frame.value for frame in frames] == [1.0, 2.0, 4.0]

    def test_linear_interpolation_between_observations(self) -> None:
        times = [T0, T0 + timedelta(days=2)]
        values = [0.0, 4.0]
        midpoint = T0 + timedelta(days=1)
        frames = interpolate_series(times, values, frame_times=[midpoint])
        assert frames[0].status is FrameStatus.INTERPOLATED
        assert frames[0].value == pytest.approx(2.0)

    def test_gap_beyond_max_is_unavailable(self) -> None:
        times = [T0, T0 + timedelta(days=100)]
        values = [1.0, 2.0]
        frames = interpolate_series(
            times, values, frame_times=[T0 + timedelta(days=50)], max_gap=timedelta(days=30)
        )
        assert frames[0].status is FrameStatus.UNAVAILABLE
        assert frames[0].value is None

    def test_no_extrapolation_by_default(self) -> None:
        times = [T0, T0 + timedelta(days=1)]
        values = [1.0, 2.0]
        frames = interpolate_series(times, values, frame_times=[T0 - timedelta(days=1)])
        assert frames[0].status is FrameStatus.UNAVAILABLE

    def test_extrapolation_only_when_enabled_and_disclosed(self) -> None:
        times = [T0, T0 + timedelta(days=1)]
        values = [1.0, 3.0]
        frames = interpolate_series(
            times, values, frame_times=[T0 + timedelta(days=2)], allow_extrapolation=True
        )
        assert frames[0].status is FrameStatus.INTERPOLATED
        assert frames[0].value == pytest.approx(5.0)

    def test_pchip_is_shape_preserving(self) -> None:
        times = [T0 + timedelta(days=d) for d in range(5)]
        values = [0.0, 1.0, 0.0, 1.0, 0.0]
        frames = interpolate_series(
            times,
            values,
            frame_times=[T0 + timedelta(days=2, hours=12)],
            method=TemporalInterpolation.PCHIP,
        )
        # PCHIP does not overshoot between 0 and 1.
        assert 0.0 <= frames[0].value <= 1.0

    def test_non_finite_values_rejected(self) -> None:
        times = [T0, T0 + timedelta(days=1)]
        with pytest.raises(ValidationError):
            interpolate_series(times, [1.0, float("nan")], frame_times=[T0])


class TestSeasonal:
    def test_monsoon_label(self) -> None:
        assert label_for(datetime(2024, 7, 1, tzinfo=UTC)) == "monsoon"
        assert label_for(datetime(2024, 1, 1, tzinfo=UTC)) == "winter"


class TestTrends:
    def test_recovers_a_known_slope(self) -> None:
        times = [T0 + timedelta(days=d) for d in range(10)]
        values = [0.5 * d for d in range(10)]
        estimate = theil_sen_trend([t.timestamp() for t in times], values, seed=1)
        assert estimate.slope_per_day == pytest.approx(0.5, abs=1e-9)
        assert estimate.ci95_per_day[0] <= 0.5 <= estimate.ci95_per_day[1]
        assert estimate.n_points == 10
        assert -1.0 <= estimate.residual_autocorr_lag1 <= 1.0

    def test_deterministic_under_seed(self) -> None:
        times = [T0 + timedelta(days=d) for d in range(8)]
        values = list(np.sin(np.arange(8) / 2.0) + 0.01 * np.arange(8))
        first = theil_sen_trend([t.timestamp() for t in times], values, seed=7)
        second = theil_sen_trend([t.timestamp() for t in times], values, seed=7)
        assert first == second


class TestChangePoints:
    def test_finds_an_obvious_change(self) -> None:
        values = [0.0] * 10 + [5.0] * 10
        report = detect_change_points(values, min_segment=5)
        assert report.change_point_indices == (10,)
        assert report.method == "binary_segmentation_mean"
        assert report.assumption == "piecewise-constant mean"

    def test_too_short_series_rejected(self) -> None:
        with pytest.raises(ValidationError):
            detect_change_points([1.0, 2.0], min_segment=5)


def _observation(index: int, station: str, value: float, sampled_at: datetime) -> Observation:
    return Observation(
        observation_id=f"obs_{index:032d}",
        dataset_id="ds_test",
        dataset_version_id="dsv_test",
        source_row=index + 2,
        source_sheet=None,
        station_id=f"stn_{station}",
        station_label=station,
        latitude_wgs84=19.7,
        longitude_wgs84=85.4,
        x_projected_m=None,
        y_projected_m=None,
        source_crs="EPSG:4326",
        analysis_crs="EPSG:32644",
        sector=None,
        sampled_at=sampled_at,
        sampling_depth_m=0.5,
        parameter_id="dissolved_oxygen",
        parameter_label="dissolved_oxygen",
        raw_value=str(value),
        raw_unit="mg/L",
        value_qualifier=ValueQualifier.MEASURED,
        canonical_value=value,
        canonical_unit="mg/L",
        detection_limit=None,
        method_id=None,
        instrument_id=None,
        qc_status=QcStatus.PASS,
        qc_flags=(),
        is_excluded=False,
        exclusion_reason=None,
        provenance_ids=(),
    )


class TestTemporalPipeline:
    def test_end_to_end_series(self) -> None:
        observations = [
            _observation(i, "St. A", 6.0 + 0.1 * i, T0 + timedelta(days=i)) for i in range(10)
        ]
        result = run_temporal_analysis(
            observations=observations,
            recipe=TemporalRecipe(resolution=TimeResolution.DAY, compute_change_points=True),
        )
        assert len(result.series) == 1
        series = result.series[0]
        assert series.alignment.observed_count == 10
        assert series.alignment.missing_count == 0
        assert all(frame.status is FrameStatus.OBSERVED for frame in series.frames)
        assert series.trend is not None
        assert series.trend.slope_per_day == pytest.approx(0.1, abs=1e-6)
        assert series.change_points is not None
        assert series.seasonal_counts  # has a season label

    def test_missing_periods_are_marked_unavailable(self) -> None:
        observations = [
            _observation(0, "St. A", 1.0, T0),
            _observation(1, "St. A", 2.0, T0 + timedelta(days=10)),
        ]
        result = run_temporal_analysis(
            observations=observations,
            recipe=TemporalRecipe(resolution=TimeResolution.DAY, max_gap_days=30),
        )
        series = result.series[0]
        statuses = {frame.status for frame in series.frames}
        assert FrameStatus.OBSERVED in statuses
        assert FrameStatus.INTERPOLATED in statuses  # the gap is within 30 days
        assert series.alignment.missing_count == 9

    def test_frame_cap_enforced(self) -> None:
        observations = [_observation(i, "St. A", 1.0, T0 + timedelta(days=i)) for i in range(30)]
        with pytest.raises(ResourceLimitError):
            run_temporal_analysis(
                observations=observations,
                recipe=TemporalRecipe(frame_count=1000),
            )
