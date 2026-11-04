"""Duplicate-location checks across stations.

Two stations registered at the same coordinates are a duplicate location: one
of them is almost certainly a data-entry copy. The check flags the later row
and keeps both rows in the dataset, because which station is wrong is a
human decision, not a pipeline one.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from trendsmapp.domain.enums import QcFlagCode
from trendsmapp.domain.models import Observation

__all__ = ["check_duplicate_locations"]

#: Rounding used to decide that two coordinates are the same place.
_COORDINATE_PRECISION: Final[int] = 6


def check_duplicate_locations(
    observations: Sequence[Observation],
) -> list[tuple[int, QcFlagCode]]:
    """Flag rows whose coordinates duplicate an earlier, different station."""
    findings: list[tuple[int, QcFlagCode]] = []
    seen: dict[tuple[float, float], str] = {}
    for index, observation in enumerate(observations):
        key = (
            round(observation.longitude_wgs84, _COORDINATE_PRECISION),
            round(observation.latitude_wgs84, _COORDINATE_PRECISION),
        )
        station = observation.station_label or ""
        if key in seen and seen[key] != station:
            findings.append((index, QcFlagCode.DUPLICATE_STATION))
        else:
            seen.setdefault(key, station)
    return findings
