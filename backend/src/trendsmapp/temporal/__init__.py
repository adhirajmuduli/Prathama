"""Public temporal exports."""

from __future__ import annotations

from trendsmapp.temporal.alignment import (
    AlignmentResult,
    TimeResolution,
    align_series,
    bucket_start,
)
from trendsmapp.temporal.change_points import (
    ChangePointReport,
    detect_change_points,
)
from trendsmapp.temporal.interpolation import (
    FrameStatus,
    InterpolatedFrame,
    interpolate_series,
)
from trendsmapp.temporal.pipeline import (
    TemporalRecipe,
    TemporalRunResult,
    TemporalSeriesResult,
    run_temporal_analysis,
)
from trendsmapp.temporal.seasonal import Season, SeasonSet, label_for, monsoon_season
from trendsmapp.temporal.trends import TrendEstimate, theil_sen_trend

__all__ = [
    "AlignmentResult",
    "ChangePointReport",
    "FrameStatus",
    "InterpolatedFrame",
    "Season",
    "SeasonSet",
    "TemporalRecipe",
    "TemporalRunResult",
    "TemporalSeriesResult",
    "TimeResolution",
    "TrendEstimate",
    "align_series",
    "bucket_start",
    "detect_change_points",
    "interpolate_series",
    "label_for",
    "monsoon_season",
    "run_temporal_analysis",
    "theil_sen_trend",
]
