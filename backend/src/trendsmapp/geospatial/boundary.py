"""Boundary GeoJSON parsing, validation, canonicalization, and hashing.

The default lagoon boundary is a versioned resource whose provenance sidecar
records the source, license, and SHA-256 of the GeoJSON. This module is the
canonical home of that loading; :mod:`trendsmapp.qc.coordinates` re-exports
:func:`load_boundary` for compatibility.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Final

from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from trendsmapp.errors import ValidationError
from trendsmapp.resources import load_yaml_resource, read_resource_bytes

__all__ = [
    "BOUNDARY_GEOJSON",
    "BOUNDARY_PROVENANCE",
    "BoundaryDocument",
    "canonical_geojson",
    "hash_geometry",
    "load_default_boundary",
    "parse_geojson_boundary",
]

#: The boundary geometry resource and its provenance sidecar.
BOUNDARY_GEOJSON: Final[str] = "default_boundary.geojson"
BOUNDARY_PROVENANCE: Final[str] = "default_boundary.provenance.v1.yaml"


@dataclass(frozen=True, slots=True)
class BoundaryDocument:
    """A validated boundary with its provenance and digest."""

    geometry: BaseGeometry
    boundary_id: str
    sha256: str
    license: str
    attribution: str
    source: str
    crs: str = "EPSG:4326"

    def contains_lonlat(self, longitude: float, latitude: float) -> bool:
        """Return whether a WGS84 point lies inside the boundary."""
        from shapely.geometry import Point

        return bool(self.geometry.covers(Point(longitude, latitude)))


def canonical_geojson(document: dict[str, Any]) -> bytes:
    """Return the canonical byte serialization of a GeoJSON document."""
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")


def hash_geometry(document: dict[str, Any]) -> str:
    """Return the SHA-256 of the canonical GeoJSON serialization."""
    return hashlib.sha256(canonical_geojson(document)).hexdigest()


def parse_geojson_boundary(
    payload: bytes, *, expected_sha256: str | None = None
) -> BoundaryDocument:
    """Parse and validate a single-feature boundary GeoJSON payload.

    When ``expected_sha256`` is given, the digest of the raw payload bytes must
    match it — this is the digest the provenance sidecar records, so a swapped
    file is rejected instead of silently used. The canonical digest of the
    parsed geometry is available separately through :func:`hash_geometry` and
    is what run manifests record.
    """
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(
            "The boundary payload is not valid GeoJSON.",
            details={"reason": "invalid_geojson"},
        ) from exc
    digest = hashlib.sha256(payload).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValidationError(
            "The boundary payload does not match the expected digest.",
            details={"expected": expected_sha256, "actual": digest},
        )
    features = document.get("features") if isinstance(document, dict) else None
    if not isinstance(features, list) or len(features) != 1:
        raise ValidationError(
            "The boundary resource must contain exactly one feature.",
            details={"reason": "invalid_boundary_features"},
        )
    feature = features[0]
    geometry_raw = feature.get("geometry") if isinstance(feature, dict) else None
    if not isinstance(geometry_raw, dict):
        raise ValidationError(
            "The boundary feature has no geometry.",
            details={"reason": "invalid_boundary_geometry"},
        )
    geometry = shape(geometry_raw)
    if not geometry.is_valid:
        # Repair is recorded through the canonical digest: a repaired geometry
        # hashes differently from the source, so the change is visible.
        geometry = geometry.buffer(0)
        if not geometry.is_valid:
            raise ValidationError(
                "The boundary geometry is not valid even after repair.",
                details={"reason": "invalid_boundary_geometry"},
            )
    properties = feature.get("properties", {}) if isinstance(feature, dict) else {}
    return BoundaryDocument(
        geometry=geometry,
        boundary_id=str(properties.get("@id", "unknown")),
        sha256=digest,
        license="",
        attribution="",
        source="",
    )


@lru_cache(maxsize=1)
def load_default_boundary() -> BoundaryDocument:
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
    document = parse_geojson_boundary(payload, expected_sha256=expected)
    return BoundaryDocument(
        geometry=document.geometry,
        boundary_id=document.boundary_id,
        sha256=document.sha256,
        license=str(provenance.get("license", "")),
        attribution=str(provenance.get("attribution", "")),
        source=str(provenance.get("source", "")),
    )
