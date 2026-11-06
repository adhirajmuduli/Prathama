"""Time alignment: explicit resolution and observed-versus-missing periods.

Alignment never invents periods. Given a resolution (hour, day, week, month),
the observed timestamps are bucketed, and every bucket in the observed span is
classified as observed or missing. Nothing outside the observed span is
produced here; extrapolation is an interpolation concern with its own rule.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final

from trendsmapp.errors import ValidationError

__all__ = ["AlignmentResult", "TimeResolution", "align_series", "bucket_start"]


class TimeResolution(StrEnum):
    """The resolutions a series can be aligned to."""

    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


#: Bucket sizes in seconds for the fixed resolutions.
_FIXED_BUCKETS: Final[dict[TimeResolution, timedelta]] = {
    TimeResolution.HOUR: timedelta(hours=1),
    TimeResolution.DAY: timedelta(days=1),
    TimeResolution.WEEK: timedelta(weeks=1),
}


@dataclass(frozen=True, slots=True)
class AlignmentResult:
    """The aligned periods of one series."""

    resolution: TimeResolution
    periods: tuple[datetime, ...]
    observed: frozenset[datetime]
    missing: tuple[datetime, ...]

    @property
    def observed_count(self) -> int:
        """Return the number of observed periods."""
        return len(self.observed)

    @property
    def missing_count(self) -> int:
        """Return the number of missing periods inside the observed span."""
        return len(self.missing)


def bucket_start(moment: datetime, resolution: TimeResolution) -> datetime:
    """Return the start of the bucket containing ``moment``."""
    if resolution is TimeResolution.MONTH:
        return moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    bucket = _FIXED_BUCKETS[resolution]
    epoch = datetime(1970, 1, 1, tzinfo=moment.tzinfo)
    seconds = (moment - epoch).total_seconds()
    bucket_seconds = bucket.total_seconds()
    start_seconds = (seconds // bucket_seconds) * bucket_seconds
    return epoch + timedelta(seconds=start_seconds)


def align_series(
    timestamps: Sequence[datetime],
    *,
    resolution: TimeResolution,
) -> AlignmentResult:
    """Bucket observed timestamps and list the missing periods in the span."""
    if not timestamps:
        raise ValidationError(
            "Alignment needs at least one observed timestamp.",
            details={"reason": "empty_series"},
        )
    buckets = sorted({bucket_start(moment, resolution) for moment in timestamps})
    observed = frozenset(buckets)
    missing: list[datetime] = []
    if resolution is TimeResolution.MONTH:
        cursor = buckets[0]
        last = buckets[-1]
        while cursor <= last:
            if cursor not in observed:
                missing.append(cursor)
            if cursor.month == 12:
                cursor = cursor.replace(year=cursor.year + 1, month=1)
            else:
                cursor = cursor.replace(month=cursor.month + 1)
    else:
        step = _FIXED_BUCKETS[resolution]
        cursor = buckets[0]
        last = buckets[-1]
        while cursor <= last:
            if cursor not in observed:
                missing.append(cursor)
            cursor += step
    return AlignmentResult(
        resolution=resolution,
        periods=tuple(buckets + missing),
        observed=observed,
        missing=tuple(missing),
    )
