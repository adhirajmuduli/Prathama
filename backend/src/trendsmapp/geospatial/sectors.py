"""Sector polygons: loading, point assignment, and ambiguity reporting.

Sectors are an optional versioned resource. When the resource is present, a
point inside exactly one sector is assigned that sector; a point inside
several sectors is reported as ambiguous instead of being assigned by
arbitrary order; a point inside none is unassigned.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Final

from shapely.geometry import Point, shape
from shapely.geometry.base import BaseGeometry

from trendsmapp.errors import ValidationError
from trendsmapp.resources import read_resource_bytes

__all__ = ["SECTOR_RESOURCE", "SectorAssignment", "SectorSet", "load_sectors"]

#: The optional sector resource.
SECTOR_RESOURCE: Final[str] = "sectors.v1.geojson"


@dataclass(frozen=True, slots=True)
class SectorAssignment:
    """The sector assignment of one point."""

    sector: str | None
    ambiguous: bool
    candidates: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SectorSet:
    """A set of named sector polygons in WGS84."""

    sectors: tuple[tuple[str, BaseGeometry], ...]

    @property
    def is_empty(self) -> bool:
        """Return whether no sectors are configured."""
        return not self.sectors

    def assign(self, longitude: float, latitude: float) -> SectorAssignment:
        """Assign a WGS84 point to a sector, reporting ambiguity explicitly."""
        point = Point(longitude, latitude)
        candidates = tuple(name for name, geometry in self.sectors if geometry.covers(point))
        if len(candidates) > 1:
            return SectorAssignment(sector=None, ambiguous=True, candidates=candidates)
        if len(candidates) == 1:
            return SectorAssignment(sector=candidates[0], ambiguous=False, candidates=candidates)
        return SectorAssignment(sector=None, ambiguous=False, candidates=())


def load_sectors() -> SectorSet:
    """Load the sector resource when it is shipped; otherwise return an empty set.

    An absent resource is not an error: sectors are optional context. A present
    but invalid resource is an error, never a silent empty set.
    """
    try:
        payload = read_resource_bytes(SECTOR_RESOURCE)
    except ValidationError:
        return SectorSet(sectors=())
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(
            f"The sector resource '{SECTOR_RESOURCE}' is not valid GeoJSON.",
            details={"reason": "invalid_sectors"},
        ) from exc
    features = document.get("features") if isinstance(document, dict) else None
    if not isinstance(features, list):
        raise ValidationError(
            f"The sector resource '{SECTOR_RESOURCE}' must be a FeatureCollection.",
            details={"reason": "invalid_sectors"},
        )
    sectors: list[tuple[str, BaseGeometry]] = []
    for feature in features:
        name = feature.get("properties", {}).get("name") if isinstance(feature, dict) else None
        geometry_raw = feature.get("geometry") if isinstance(feature, dict) else None
        if not isinstance(name, str) or not isinstance(geometry_raw, dict):
            continue
        geometry = shape(geometry_raw)
        if geometry.is_valid:
            sectors.append((name, geometry))
    return SectorSet(sectors=tuple(sectors))
