"""WGS84 validation and projected-coordinate derivation.

Latitude and longitude remain the WGS84 fields of an observation; projected
coordinates are derived from them and recorded separately, never written
back over the geographic ones. When the source file already carries projected
coordinates, the inverse transform derives the WGS84 pair, and the source CRS
is recorded so the derivation is auditable.

Out-of-range or non-finite coordinates are not hard errors here: they are
returned as issues with ``None`` fields, so quality control can flag them
while the raw value stays in the dataset.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Final

from pyproj import CRS, Transformer
from pyproj.exceptions import CRSError, ProjError

from trendsmapp.constants import DEFAULT_ANALYSIS_CRS
from trendsmapp.errors import ValidationError

__all__ = [
    "CoordinateResult",
    "normalize_projected",
    "normalize_wgs84",
]

#: WGS84 axis bounds.
MAX_LATITUDE: Final[float] = 90.0
MAX_LONGITUDE: Final[float] = 180.0


@dataclass(frozen=True, slots=True)
class CoordinateResult:
    """The geographic and projected coordinates of one observation."""

    latitude: float | None
    longitude: float | None
    x_projected_m: float | None
    y_projected_m: float | None
    source_crs: str
    analysis_crs: str
    issues: tuple[str, ...]


def normalize_wgs84(
    latitude_text: str,
    longitude_text: str,
    *,
    analysis_crs: str = DEFAULT_ANALYSIS_CRS,
    source_crs: str = "EPSG:4326",
) -> CoordinateResult:
    """Validate WGS84 text and derive the projected coordinates."""
    issues: list[str] = []
    latitude = _parse_coordinate(latitude_text, "latitude", issues)
    longitude = _parse_coordinate(longitude_text, "longitude", issues)
    if latitude is not None and not -MAX_LATITUDE <= latitude <= MAX_LATITUDE:
        issues.append("coordinate_out_of_range: latitude")
        latitude = None
    if longitude is not None and not -MAX_LONGITUDE <= longitude <= MAX_LONGITUDE:
        issues.append("coordinate_out_of_range: longitude")
        longitude = None

    x = y = None
    if latitude is not None and longitude is not None:
        x, y = _project(longitude, latitude, source_crs, analysis_crs, issues)
    return CoordinateResult(
        latitude=latitude,
        longitude=longitude,
        x_projected_m=x,
        y_projected_m=y,
        source_crs=source_crs,
        analysis_crs=analysis_crs,
        issues=tuple(issues),
    )


def normalize_projected(
    easting_text: str,
    northing_text: str,
    *,
    source_crs: str,
    analysis_crs: str = DEFAULT_ANALYSIS_CRS,
) -> CoordinateResult:
    """Take projected source coordinates, derive WGS84 and the analysis CRS."""
    issues: list[str] = []
    easting = _parse_coordinate(easting_text, "easting", issues)
    northing = _parse_coordinate(northing_text, "northing", issues)
    latitude = longitude = None
    if easting is not None and northing is not None:
        longitude, latitude = _project(easting, northing, source_crs, "EPSG:4326", issues)
    x = y = None
    if easting is not None and northing is not None:
        x, y = _project(easting, northing, source_crs, analysis_crs, issues)
    return CoordinateResult(
        latitude=latitude,
        longitude=longitude,
        x_projected_m=x,
        y_projected_m=y,
        source_crs=source_crs,
        analysis_crs=analysis_crs,
        issues=tuple(issues),
    )


def _parse_coordinate(text: str, name: str, issues: list[str]) -> float | None:
    """Parse one coordinate, recording non-finite and unparsable values."""
    raw = text.strip()
    if not raw:
        issues.append(f"missing_coordinate: {name}")
        return None
    try:
        value = float(raw)
    except ValueError:
        issues.append(f"invalid_coordinate: {name}")
        return None
    if not math.isfinite(value):
        issues.append(f"non_finite_coordinate: {name}")
        return None
    return value


def _project(
    x: float,
    y: float,
    source_crs: str,
    target_crs: str,
    issues: list[str],
) -> tuple[float | None, float | None]:
    """Transform one point, recording failures instead of crashing the parse."""
    try:
        transformer = _transformer(source_crs, target_crs)
        result_x, result_y = transformer.transform(x, y)
    except (CRSError, ValidationError):
        raise
    except ProjError:
        issues.append("projection_failed")
        return None, None
    if not (math.isfinite(result_x) and math.isfinite(result_y)):
        issues.append("projection_non_finite")
        return None, None
    return result_x, result_y


@lru_cache(maxsize=64)
def _transformer(source_crs: str, target_crs: str) -> Transformer:
    """Return a cached transformer, validating both CRS strings first."""
    try:
        source = CRS.from_user_input(source_crs)
        target = CRS.from_user_input(target_crs)
    except CRSError as exc:
        raise ValidationError(
            f"'{exc}' is not a valid coordinate reference system.",
            details={"reason": "invalid_crs"},
        ) from exc
    if source == target:
        return Transformer.from_crs(source, target, always_xy=True)
    return Transformer.from_crs(source, target, always_xy=True)
