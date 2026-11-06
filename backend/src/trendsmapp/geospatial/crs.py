"""CRS validation, cached transformers, and axis-order safety.

Every spatial computation in this project happens in a projected CRS. This
module is the single place where CRS strings are validated and transformers
are created. Transformers are always built with ``always_xy=True`` so that
coordinates are passed and returned as (easting, northing) regardless of the
axis order the CRS definition declares, which removes a whole class of
silent transposition bugs.
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache

import numpy as np
from pyproj import CRS, Transformer
from pyproj.exceptions import CRSError

from trendsmapp.constants import DEFAULT_ANALYSIS_CRS
from trendsmapp.errors import ValidationError

__all__ = [
    "DEFAULT_ANALYSIS_CRS",
    "to_analysis_crs",
    "transform_points",
    "transformer_for",
    "validate_crs",
]

#: The CRS all analysis grids are built in.
# Re-exported from constants for convenience.


def validate_crs(crs_text: str) -> CRS:
    """Return the parsed CRS, raising a coded error for an invalid one."""
    if not isinstance(crs_text, str) or not crs_text.strip():
        raise ValidationError(
            "A CRS string is required.",
            details={"reason": "missing_crs"},
        )
    try:
        return CRS.from_user_input(crs_text.strip())
    except CRSError as exc:
        raise ValidationError(
            f"'{crs_text}' is not a valid coordinate reference system.",
            details={"reason": "invalid_crs", "crs": crs_text},
        ) from exc


@lru_cache(maxsize=64)
def transformer_for(source_crs: str, target_crs: str) -> Transformer:
    """Return a cached always-XY transformer between two CRS strings."""
    source = validate_crs(source_crs)
    target = validate_crs(target_crs)
    return Transformer.from_crs(source, target, always_xy=True)


def transform_points(
    points: np.ndarray,
    *,
    source_crs: str,
    target_crs: str,
) -> np.ndarray:
    """Transform an (N, 2) array of (x, y) points between CRS strings."""
    if points.ndim != 2 or points.shape[1] != 2:
        raise ValidationError(
            "Points must be an (N, 2) array.",
            details={"reason": "invalid_points_shape", "shape": list(points.shape)},
        )
    if len(points) == 0:
        return np.empty((0, 2), dtype=float)
    transformer = transformer_for(source_crs, target_crs)
    x, y = transformer.transform(points[:, 0], points[:, 1])
    return np.column_stack([np.asarray(x, dtype=float), np.asarray(y, dtype=float)])


def to_analysis_crs(
    points_wgs84_lonlat: Sequence[tuple[float, float]] | np.ndarray,
    *,
    source_crs: str = "EPSG:4326",
    analysis_crs: str = DEFAULT_ANALYSIS_CRS,
) -> np.ndarray:
    """Transform WGS84 (lon, lat) pairs into the analysis CRS."""
    array = np.asarray(points_wgs84_lonlat, dtype=float).reshape(-1, 2)
    return transform_points(array, source_crs=source_crs, target_crs=analysis_crs)
