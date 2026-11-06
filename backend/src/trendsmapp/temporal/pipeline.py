"""The temporal pipeline: aligned series, interpolated frames, seasonal and trend artifacts.

The pipeline produces, per (station, parameter): the aligned series with
observed/missing periods, the interpolated frame inputs (each marked
observed, interpolated, or unavailable), the seasonal summary, and the trend
estimate. All outputs are deterministic for the same inputs and seed.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, cast

import numpy as np

from trendsmapp.domain.enums import TemporalInterpolation
from trendsmapp.domain.models import Observation
from trendsmapp.errors import ResourceLimitError
from trendsmapp.temporal.alignment import (
    AlignmentResult,
    TimeResolution,
    align_series,
    bucket_start,
)
from trendsmapp.temporal.change_points import ChangePointReport, detect_change_points
from trendsmapp.temporal.interpolation import (
    DEFAULT_MAX_GAP_DAYS,
    FrameStatus,
    InterpolatedFrame,
    interpolate_series,
)
from trendsmapp.temporal.seasonal import label_for
from trendsmapp.temporal.trends import TrendEstimate, theil_sen_trend

__all__ = [
    "TemporalRecipe",
    "TemporalRunResult",
    "TemporalSeriesResult",
    "run_temporal_analysis",
]

#: Maximum frames produced per series.
MAX_FRAMES_PER_SERIES: Final[int] = 900


@dataclass(frozen=True, slots=True)
class TemporalRecipe:
    """The temporal section of an analysis recipe."""

    resolution: TimeResolution = TimeResolution.DAY
    interpolation: TemporalInterpolation = TemporalInterpolation.LINEAR
    max_gap_days: float = DEFAULT_MAX_GAP_DAYS
    allow_extrapolation: bool = False
    frame_count: int = 0  # 0 = every aligned period
    compute_trends: bool = True
    compute_change_points: bool = False
    seed: int = 0

    def __post_init__(self) -> None:
        if self.frame_count < 0 or self.frame_count > MAX_FRAMES_PER_SERIES:
            raise ResourceLimitError(
                "The frame count is outside the accepted bounds.",
                details={"frame_count": self.frame_count, "max": MAX_FRAMES_PER_SERIES},
            )


@dataclass(frozen=True, slots=True)
class TemporalSeriesResult:
    """One (station, parameter) series result."""

    station_id: str
    parameter_id: str
    alignment: AlignmentResult
    frames: tuple[InterpolatedFrame, ...]
    trend: TrendEstimate | None
    change_points: ChangePointReport | None
    seasonal_counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class TemporalRunResult:
    """The outcome of one temporal run."""

    series: tuple[TemporalSeriesResult, ...]


def run_temporal_analysis(
    *,
    observations: Sequence[Observation],
    recipe: TemporalRecipe,
) -> TemporalRunResult:
    """Run the temporal pipeline over the observations of one dataset version."""
    groups: dict[tuple[str, str], list[Observation]] = {}
    for observation in observations:
        if observation.canonical_value is None or observation.is_excluded:
            continue
        if not observation.parameter_id:
            continue
        groups.setdefault((observation.station_id, observation.parameter_id), []).append(
            observation
        )

    results: list[TemporalSeriesResult] = []
    for (station_id, parameter_id), members in sorted(groups.items()):
        members = [o for o in members if o.canonical_value is not None]
        members.sort(key=lambda o: o.sampled_at)
        timestamps = [o.sampled_at for o in members]
        values = [cast(float, o.canonical_value) for o in members]
        alignment = align_series(timestamps, resolution=recipe.resolution)

        frame_times = list(alignment.periods)
        if recipe.frame_count > 0:
            step = max(1, len(frame_times) // recipe.frame_count)
            frame_times = frame_times[::step][: recipe.frame_count]
        if len(frame_times) > MAX_FRAMES_PER_SERIES:
            raise ResourceLimitError(
                "The series would produce more frames than the per-series cap.",
                details={"frames": len(frame_times), "max": MAX_FRAMES_PER_SERIES},
            )
        frames = interpolate_series(
            timestamps,
            values,
            frame_times=frame_times,
            method=recipe.interpolation,
            max_gap=timedelta(days=recipe.max_gap_days),
            allow_extrapolation=recipe.allow_extrapolation,
        )
        # A frame whose bucket contains an observed timestamp is observed, with
        # the bucket's mean value; the interpolator only sees bucket starts.
        bucket_values: dict[datetime, list[float]] = {}
        for moment, value in zip(timestamps, values, strict=True):
            bucket_values.setdefault(bucket_start(moment, recipe.resolution), []).append(value)
        frames = [
            (
                InterpolatedFrame(
                    timestamp=frame.timestamp,
                    value=float(
                        np.mean(bucket_values[bucket_start(frame.timestamp, recipe.resolution)])
                    ),
                    status=FrameStatus.OBSERVED,
                )
                if bucket_start(frame.timestamp, recipe.resolution) in bucket_values
                else frame
            )
            for frame in frames
        ]

        seasonal_counts = _seasonal_counts(timestamps)
        trend = None
        if recipe.compute_trends and len(timestamps) >= 3:
            trend = theil_sen_trend([t.timestamp() for t in timestamps], values, seed=recipe.seed)
        change_points = None
        if recipe.compute_change_points:
            change_points = detect_change_points(values)

        results.append(
            TemporalSeriesResult(
                station_id=station_id,
                parameter_id=parameter_id,
                alignment=alignment,
                frames=tuple(frames),
                trend=trend,
                change_points=change_points,
                seasonal_counts=seasonal_counts,
            )
        )
    return TemporalRunResult(series=tuple(results))


def _seasonal_counts(timestamps: Sequence[datetime]) -> dict[str, int]:
    """Count observations per season label."""
    counts: dict[str, int] = {}
    for moment in timestamps:
        label = label_for(moment)
        counts[label or "unlabeled"] = counts.get(label or "unlabeled", 0) + 1
    return dict(sorted(counts.items()))
