"""Coordinate quality control: boundary, duplicate locations, station drift.

The default boundary is a versioned resource with a provenance sidecar. The
loader refuses to use it unless the SHA-256 of the GeoJSON matches the digest
recorded in the sidecar, so the boundary can never be swapped silently. Every
check produces flags; no observation is removed here.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Final

from shapely.geometry import Point, shape
from shapely.geometry.base import BaseGeometry

from trendsmapp.domain.enums import QcFlagCode
from trendsmapp.domain.models import Observation
from trendsmapp.errors import ValidationError
from trendsmapp.resources import load_yaml_resource, read_resource_bytes

__all__ = [
    "BOUNDARY_GEOJSON",
    "BOUNDARY_PROVENANCE",
    "Boundary",
    "check_coordinates",
    "load_boundary",
]

#: The boundary geometry resource and its provenance sidecar.
BOUNDARY_GEOJSON: Final[str] = "default_boundary.geojson"
BOUNDARY_PROVENANCE: Final[str] = "default_boundary.provenance.v1.yaml"

#: A station whose coordinates move more than this many metres between visits
#: has drifted.
_STATION_DRIFT_METRES: Final[float] = 500.0


@dataclass(frozen=True, slots=True)
class Boundary:
    """A validated boundary polygon with its provenance."""

    geometry: BaseGeometry
    boundary_id: str
    sha256: str
    license: str
    attribution: str
    source: str

    def contains(self, longitude: float, latitude: float) -> bool:
        """Return whether a WGS84 point lies inside the boundary."""
        return bool(self.geometry.covers(Point(longitude, latitude)))


@lru_cache(maxsize=1)
def load_boundary() -> Boundary:
    """Load the default boundary, verifying its provenance digest."""
    provenance = load_yaml_resource(BOUNDARY_PROVENANCE)
    expected = provenance.get("sha256")
    resource_name = provenance.get("resource")
    if not isinstance(expected, str) or not expected:
        raise ValidationError(
            f"The provenance sidecar '{BOUNDARY_PROVENANCE}' must record a sha256.",
            details={"name": BOUNDARY_PROVENANCE},
        )
    if resource_name != BOUNDARY_GEOJSON:
        raise ValidationError(
            f"The provenance sidecar points at '{resource_name}', not '{BOUNDARY_GEOJSON}'.",
            details={"name": BOUNDARY_PROVENANCE},
        )
    payload = read_resource_bytes(BOUNDARY_GEOJSON)
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected:
        raise ValidationError(
            f"The boundary resource '{BOUNDARY_GEOJSON}' does not match the "
            "provenance digest; the file was changed without updating "
            f"'{BOUNDARY_PROVENANCE}'.",
            details={
                "expected": expected,
                "actual": actual,
                "name": BOUNDARY_GEOJSON,
            },
        )
    try:
        document = json.loads(payload.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValidationError(
            f"The boundary resource '{BOUNDARY_GEOJSON}' is not valid GeoJSON.",
            details={"name": BOUNDARY_GEOJSON},
        ) from exc
    features = document.get("features") if isinstance(document, dict) else None
    if not isinstance(features, list) or len(features) != 1:
        raise ValidationError(
            "The boundary resource must contain exactly one feature.",
            details={"name": BOUNDARY_GEOJSON},
        )
    geometry = shape(features[0]["geometry"])
    if not geometry.is_valid:
        geometry = geometry.buffer(0)
    properties = features[0].get("properties", {})
    boundary_id = str(properties.get("@id", "unknown"))
    return Boundary(
        geometry=geometry,
        boundary_id=boundary_id,
        sha256=actual,
        license=str(provenance.get("license", "")),
        attribution=str(provenance.get("attribution", "")),
        source=str(provenance.get("source", "")),
    )


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
            if not boundary.contains(observation.longitude_wgs84, observation.latitude_wgs84):
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
