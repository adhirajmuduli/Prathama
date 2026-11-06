"""Coordinate quality control: boundary, duplicate locations, station drift.

The default boundary is a versioned resource with a provenance sidecar. The
canonical loader lives in :mod:	rendsmapp.geospatial.boundary and is
re-exported here for compatibility. Every check produces flags; no observation
is removed here.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from trendsmapp.domain.enums import QcFlagCode
from trendsmapp.domain.models import Observation
from trendsmapp.geospatial.boundary import (
    BOUNDARY_GEOJSON,
    BOUNDARY_PROVENANCE,
    BoundaryDocument,
    load_default_boundary,
)

# Backward-compatible aliases: the boundary API moved to geospatial.boundary.
Boundary = BoundaryDocument
load_boundary = load_default_boundary

__all__ = [
    "BOUNDARY_GEOJSON",
    "BOUNDARY_PROVENANCE",
    "Boundary",
    "check_coordinates",
    "load_boundary",
]

#: A station whose coordinates move more than this many metres between visits
#: has drifted.
_STATION_DRIFT_METRES: Final[float] = 500.0


def check_coordinates(
    observations: Sequence[Observation],
    boundary: Boundary | None = None,
    *,
    station_drift_metres: float = _STATION_DRIFT_METRES,
) -> list[tuple[int, QcFlagCode, str]]:
    """Flag boundary and station-drift problems.

    Returns ``(observation_index, flag, detail)`` triples. The boundary check
    is skipped when no boundary is supplied. Station drift is found by
    comparing the projected coordinates of one station label across its
    visits. Duplicate locations between different stations are a separate rule
    (:mod:`trendsmapp.qc.duplicates`), because they need the station labels.
    """
    findings: list[tuple[int, QcFlagCode, str]] = []

    if boundary is not None:
        for index, observation in enumerate(observations):
            if not boundary.contains_lonlat(
                observation.longitude_wgs84, observation.latitude_wgs84
            ):
                findings.append((index, QcFlagCode.OUTSIDE_BOUNDARY, boundary.boundary_id))

    by_station: dict[str, list[tuple[int, float, float]]] = {}
    for index, observation in enumerate(observations):
        if observation.x_projected_m is None or observation.y_projected_m is None:
            continue
        by_station.setdefault(observation.station_label or "", []).append(
            (index, observation.x_projected_m, observation.y_projected_m)
        )
    for station, visits in by_station.items():
        if len(visits) < 2:
            continue
        first_index, first_x, first_y = visits[0]
        for index, x, y in visits[1:]:
            distance = ((x - first_x) ** 2 + (y - first_y) ** 2) ** 0.5
            if distance > station_drift_metres:
                findings.append(
                    (
                        index,
                        QcFlagCode.STATION_DRIFT,
                        f"station '{station}' moved {distance:.0f} m from row {first_index}",
                    )
                )
    return findings
