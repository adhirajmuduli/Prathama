"""Temporal interpolation: linear and PCHIP with maximum-gap constraints.

Interpolation only ever fills gaps inside the observed span whose duration is
within the configured maximum. Extrapolation outside the observed span is
off by default; when enabled it is disclosed in the frame metadata. Every
produced frame is marked observed, interpolated, or unavailable.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final

import numpy as np

from trendsmapp.domain.enums import TemporalInterpolation
from trendsmapp.errors import ValidationError

__all__ = [
    "FrameStatus",
    "InterpolatedFrame",
    "interpolate_series",
]


class FrameStatus(StrEnum):
    """The provenance status of one produced frame."""

    OBSERVED = "observed"
    INTERPOLATED = "interpolated"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class InterpolatedFrame:
    """One produced time frame."""

    timestamp: datetime
    value: float | None
    status: FrameStatus


#: Default maximum gap, in days, that may be interpolated across.
DEFAULT_MAX_GAP_DAYS: Final[float] = 60.0


def interpolate_series(
    timestamps: Sequence[datetime],
    values: Sequence[float],
    *,
    frame_times: Sequence[datetime],
    method: TemporalInterpolation = TemporalInterpolation.LINEAR,
    max_gap: timedelta = timedelta(days=DEFAULT_MAX_GAP_DAYS),
    allow_extrapolation: bool = False,
) -> list[InterpolatedFrame]:
    """Interpolate a series onto ``frame_times`` under the gap and span rules.

    A frame inside the observed span whose surrounding observations are closer
    than ``max_gap`` is interpolated and marked ``interpolated``; a frame at an
    observed timestamp is ``observed``; anything else is ``unavailable`` with
    a null value. Extrapolated frames (outside the span) are produced only when
    ``allow_extrapolation`` is true, and are marked ``interpolated`` so the
    disclosure travels with the frame.
    """
    if len(timestamps) != len(values):
        raise ValidationError(
            "timestamps and values must align.",
            details={"timestamps": len(timestamps), "values": len(values)},
        )
    if len(timestamps) < 2:
        raise ValidationError(
            "Interpolation needs at least two observed points.",
            details={"points": len(timestamps)},
        )
    order = sorted(range(len(timestamps)), key=lambda i: timestamps[i])
    times = [timestamps[i] for i in order]
    vals = np.asarray([values[i] for i in order], dtype=float)
    if np.any(~np.isfinite(vals)):
        raise ValidationError(
            "Non-finite values cannot be interpolated; they are flagged by QC.",
            details={"reason": "non_finite_values"},
        )
    t_numeric = np.asarray([t.timestamp() for t in times], dtype=float)
    first, last = times[0], times[-1]

    frames: list[InterpolatedFrame] = []
    for frame_time in frame_times:
        if frame_time in set(times):
            index = times.index(frame_time)
            frames.append(
                InterpolatedFrame(
                    timestamp=frame_time, value=float(vals[index]), status=FrameStatus.OBSERVED
                )
            )
            continue
        if frame_time < first or frame_time > last:
            if allow_extrapolation:
                value = _interpolate(method, t_numeric, vals, frame_time.timestamp())
                frames.append(
                    InterpolatedFrame(
                        timestamp=frame_time, value=float(value), status=FrameStatus.INTERPOLATED
                    )
                )
            else:
                frames.append(
                    InterpolatedFrame(
                        timestamp=frame_time, value=None, status=FrameStatus.UNAVAILABLE
                    )
                )
            continue
        # inside the span: find the bracketing observations
        right = int(np.searchsorted(t_numeric, frame_time.timestamp(), side="right"))
        left = right - 1
        gap = times[right] - times[left]
        if gap > max_gap:
            frames.append(
                InterpolatedFrame(timestamp=frame_time, value=None, status=FrameStatus.UNAVAILABLE)
            )
            continue
        value = _interpolate(
            method, t_numeric, vals, frame_time.timestamp(), left=left, right=right
        )
        frames.append(
            InterpolatedFrame(
                timestamp=frame_time, value=float(value), status=FrameStatus.INTERPOLATED
            )
        )
    return frames


def _interpolate(
    method: TemporalInterpolation,
    t_numeric: np.ndarray,
    values: np.ndarray,
    target: float,
    *,
    left: int | None = None,
    right: int | None = None,
) -> float:
    """Interpolate one target timestamp with the selected method."""
    if method is TemporalInterpolation.PCHIP:
        from scipy.interpolate import PchipInterpolator

        model = PchipInterpolator(t_numeric, values)
        return float(model(target))
    # linear, including the extrapolation case where the bracket is the edge
    if left is None or right is None:
        # extrapolate with the edge segment slope
        if target < t_numeric[0]:
            slope = (values[1] - values[0]) / (t_numeric[1] - t_numeric[0])
            return float(values[0] + slope * (target - t_numeric[0]))
        slope = (values[-1] - values[-2]) / (t_numeric[-1] - t_numeric[-2])
        return float(values[-1] + slope * (target - t_numeric[-1]))
    t0, t1 = t_numeric[left], t_numeric[right]
    v0, v1 = values[left], values[right]
    if t1 == t0:
        return float(v0)
    return float(v0 + (v1 - v0) * (target - t0) / (t1 - t0))
