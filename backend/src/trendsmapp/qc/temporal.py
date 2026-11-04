"""Temporal checks: sampling gaps, repeated visits, abrupt jumps.

Within each (station, parameter) series sorted by time, three things are
checked: a gap much larger than the median interval (``sampling_gap``), a
repeated visit inside the minimum plausible interval (``repeated_visit``), and
an abrupt change between consecutive values (``abrupt_jump``). All thresholds
are derived from the series itself and recorded, so the same dataset always
produces the same flags.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from typing import Final

from trendsmapp.domain.enums import QcFlagCode
from trendsmapp.domain.models import Observation

__all__ = [
    "GAP_FACTOR",
    "JUMP_FACTOR",
    "MIN_SERIES_SIZE",
    "check_temporal",
]

#: A gap larger than this multiple of the median interval is flagged.
GAP_FACTOR: Final[float] = 3.0

#: A change larger than this multiple of the series MAD is an abrupt jump.
JUMP_FACTOR: Final[float] = 6.0

#: Smallest series that supports temporal checks.
MIN_SERIES_SIZE: Final[int] = 3

#: Repeated visits closer than this fraction of the median interval are flagged.
_REPEAT_FACTOR: Final[float] = 0.25


def check_temporal(
    observations: Sequence[Observation],
    *,
    gap_factor: float = GAP_FACTOR,
    jump_factor: float = JUMP_FACTOR,
    min_series_size: int = MIN_SERIES_SIZE,
) -> tuple[list[tuple[int, QcFlagCode, str]], list[str]]:
    """Flag temporal problems in each (station, parameter) series.

    Returns findings as ``(index, flag, detail)`` and notes for skipped series.
    """
    series: dict[tuple[str, str], list[tuple[int, datetime, float | None]]] = defaultdict(list)
    for index, observation in enumerate(observations):
        if not observation.parameter_id:
            continue
        series[(observation.station_label or "", observation.parameter_id)].append(
            (index, observation.sampled_at, observation.canonical_value)
        )

    findings: list[tuple[int, QcFlagCode, str]] = []
    notes: list[str] = []
    for (station, parameter_id), entries in sorted(series.items()):
        if len(entries) < min_series_size:
            notes.append(
                f"series {station}/{parameter_id} has {len(entries)} points; "
                f"temporal checks need at least {min_series_size}"
            )
            continue
        entries.sort(key=lambda item: item[1])
        intervals = [
            (entries[i + 1][1] - entries[i][1]).total_seconds() for i in range(len(entries) - 1)
        ]
        intervals = [value for value in intervals if value > 0]
        if not intervals:
            notes.append(f"series {station}/{parameter_id} has no positive time intervals")
            continue
        median_interval = statistics.median(intervals)
        for i in range(1, len(entries)):
            gap = (entries[i][1] - entries[i - 1][1]).total_seconds()
            if gap <= 0:
                findings.append(
                    (
                        entries[i][0],
                        QcFlagCode.REPEATED_VISIT,
                        f"{gap:.0f} s after the previous visit",
                    )
                )
                continue
            if gap > gap_factor * median_interval:
                findings.append(
                    (
                        entries[i][0],
                        QcFlagCode.SAMPLING_GAP,
                        f"{gap:.0f} s gap, median interval {median_interval:.0f} s",
                    )
                )
            elif gap < _REPEAT_FACTOR * median_interval:
                findings.append(
                    (
                        entries[i][0],
                        QcFlagCode.REPEATED_VISIT,
                        f"{gap:.0f} s after the previous visit, below the repeat threshold",
                    )
                )
        values = [value for _, _, value in entries if value is not None]
        if len(values) >= 2:
            median_value = statistics.median(values)
            mad = statistics.median([abs(value - median_value) for value in values])
            scale = mad if mad > 0 else (max(values) - min(values) or 1.0)
            for i in range(1, len(entries)):
                previous = entries[i - 1][2]
                current = entries[i][2]
                if previous is None or current is None:
                    continue
                change = abs(current - previous)
                if change > jump_factor * scale:
                    findings.append(
                        (
                            entries[i][0],
                            QcFlagCode.ABRUPT_JUMP,
                            f"change of {change:.3g} from the previous value",
                        )
                    )
    return findings, notes
