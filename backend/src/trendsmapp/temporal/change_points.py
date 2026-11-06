"""Optional change-point analysis with declared assumptions and segment limits.

The method is binary segmentation on the mean: it repeatedly splits the
series at the point that most reduces the residual sum of squares, stopping at
the configured minimum segment length and maximum number of change points.
The report always states the method, its assumption (piecewise-constant mean),
and the minimum segment limit, so a reader knows what was and was not assumed.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np

from trendsmapp.errors import ValidationError

__all__ = ["ChangePointReport", "detect_change_points"]

#: Minimum points per segment.
DEFAULT_MIN_SEGMENT: Final[int] = 5

#: Maximum change points reported.
DEFAULT_MAX_CHANGE_POINTS: Final[int] = 10


@dataclass(frozen=True, slots=True)
class ChangePointReport:
    """The change points found, with the method's declared assumptions."""

    change_point_indices: tuple[int, ...]
    method: str = "binary_segmentation_mean"
    assumption: str = "piecewise-constant mean"
    min_segment_points: int = DEFAULT_MIN_SEGMENT
    max_change_points: int = DEFAULT_MAX_CHANGE_POINTS


def detect_change_points(
    values: Sequence[float],
    *,
    min_segment: int = DEFAULT_MIN_SEGMENT,
    max_change_points: int = DEFAULT_MAX_CHANGE_POINTS,
) -> ChangePointReport:
    """Detect change points in a series by binary segmentation on the mean."""
    v = np.asarray(values, dtype=float)
    if len(v) < 2 * min_segment:
        raise ValidationError(
            "The series is too short for the minimum segment length.",
            details={"points": len(v), "min_segment": min_segment},
        )
    if np.any(~np.isfinite(v)):
        raise ValidationError(
            "Non-finite values cannot be analyzed for change points.",
            details={"reason": "non_finite_values"},
        )
    found: list[int] = []

    def _best_split(segment: np.ndarray) -> tuple[int, float] | None:
        """Return the best split index and its RSS reduction within a segment."""
        n = len(segment)
        if n < 2 * min_segment:
            return None
        total_mean = segment.mean()
        total_rss = float(((segment - total_mean) ** 2).sum())
        best_index = -1
        best_gain = 0.0
        for cut in range(min_segment, n - min_segment + 1):
            left = segment[:cut]
            right = segment[cut:]
            rss = float(((left - left.mean()) ** 2).sum() + ((right - right.mean()) ** 2).sum())
            gain = total_rss - rss
            if gain > best_gain:
                best_gain = gain
                best_index = cut
        if best_index < 0:
            return None
        return best_index, best_gain

    segments = [(0, len(v))]
    while len(found) < max_change_points and segments:
        best: tuple[int, int, float] | None = None
        for start, end in segments:
            result = _best_split(v[start:end])
            if result is None:
                continue
            cut, gain = result
            if best is None or gain > best[2]:
                best = (start + cut, start, gain)
        if best is None:
            break
        cut, start, _gain = best
        found.append(cut)
        end = next(e for s, e in segments if s == start)
        segments.remove((start, end))
        segments.append((start, cut))
        segments.append((cut, end))

    return ChangePointReport(
        change_point_indices=tuple(sorted(found)),
        min_segment_points=min_segment,
        max_change_points=max_change_points,
    )
