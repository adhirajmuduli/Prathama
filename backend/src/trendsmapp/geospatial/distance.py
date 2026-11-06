"""Projected Euclidean distances and optional geodesic diagnostics.

Planar distances are only ever computed in a projected CRS — never on raw
longitude/latitude. Geodesic distances are available for diagnostics and are
always labelled as such.
"""

from __future__ import annotations

import numpy as np
from pyproj import Geod

from trendsmapp.errors import ValidationError
from trendsmapp.geospatial.crs import validate_crs

__all__ = [
    "euclidean_distance_matrix",
    "geodesic_distance_matrix",
    "nearest_neighbor_distances",
    "pairwise_distances",
]


def _check_projected(crs: str) -> None:
    """Raise when a CRS is geographic (degrees), where planar distance is wrong."""
    parsed = validate_crs(crs)
    if parsed.is_geographic:
        raise ValidationError(
            "Planar distances must be computed in a projected CRS, not in degrees.",
            details={"crs": crs, "reason": "geographic_crs_for_planar_distance"},
        )


def pairwise_distances(a: np.ndarray, b: np.ndarray, *, crs: str) -> np.ndarray:
    """Return the (len(a), len(b)) matrix of planar distances in ``crs``."""
    _check_projected(crs)
    a = np.asarray(a, dtype=float).reshape(-1, 2)
    b = np.asarray(b, dtype=float).reshape(-1, 2)
    diff = a[:, None, :] - b[None, :, :]
    matrix: np.ndarray = np.sqrt((diff**2).sum(axis=2))
    return matrix


def euclidean_distance_matrix(points: np.ndarray, *, crs: str) -> np.ndarray:
    """Return the (N, N) pairwise planar distance matrix in ``crs``."""
    return pairwise_distances(points, points, crs=crs)


def nearest_neighbor_distances(points: np.ndarray, *, crs: str) -> np.ndarray:
    """Return the distance from each point to its nearest other point."""
    matrix = euclidean_distance_matrix(points, crs=crs)
    if matrix.shape[0] < 2:
        return np.zeros(len(points), dtype=float)
    np.fill_diagonal(matrix, np.inf)
    return matrix.min(axis=1)


def geodesic_distance_matrix(lonlat: np.ndarray) -> np.ndarray:
    """Return the (N, N) geodesic distance matrix in metres for (lon, lat) pairs.

    This is a diagnostic only; it is never used as an interpolation distance.
    """
    points = np.asarray(lonlat, dtype=float).reshape(-1, 2)
    geod = Geod(ellps="WGS84")
    lons = points[:, 0]
    lats = points[:, 1]
    _, _, distances = geod.inv(
        np.repeat(lons, len(points)),
        np.repeat(lats, len(points)),
        np.tile(lons, len(points)),
        np.tile(lats, len(points)),
    )
    return np.asarray(distances, dtype=float).reshape(len(points), len(points))
