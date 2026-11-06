"""Stable geospatial utility exports."""

from __future__ import annotations

from trendsmapp.geospatial.boundary import (
    BOUNDARY_GEOJSON,
    BOUNDARY_PROVENANCE,
    BoundaryDocument,
    canonical_geojson,
    hash_geometry,
    load_default_boundary,
    parse_geojson_boundary,
)
from trendsmapp.geospatial.crs import (
    DEFAULT_ANALYSIS_CRS,
    to_analysis_crs,
    transform_points,
    transformer_for,
    validate_crs,
)
from trendsmapp.geospatial.distance import (
    euclidean_distance_matrix,
    geodesic_distance_matrix,
    nearest_neighbor_distances,
    pairwise_distances,
)
from trendsmapp.geospatial.grid import GRID_CELL_LIMITS, Grid, build_grid
from trendsmapp.geospatial.masking import NODATA, apply_nodata, lagoon_mask, masked_array
from trendsmapp.geospatial.sectors import (
    SECTOR_RESOURCE,
    SectorAssignment,
    SectorSet,
    load_sectors,
)

__all__ = [
    "BOUNDARY_GEOJSON",
    "BOUNDARY_PROVENANCE",
    "DEFAULT_ANALYSIS_CRS",
    "GRID_CELL_LIMITS",
    "NODATA",
    "SECTOR_RESOURCE",
    "BoundaryDocument",
    "Grid",
    "SectorAssignment",
    "SectorSet",
    "apply_nodata",
    "build_grid",
    "canonical_geojson",
    "euclidean_distance_matrix",
    "geodesic_distance_matrix",
    "hash_geometry",
    "lagoon_mask",
    "load_default_boundary",
    "load_sectors",
    "masked_array",
    "nearest_neighbor_distances",
    "pairwise_distances",
    "parse_geojson_boundary",
    "to_analysis_crs",
    "transform_points",
    "transformer_for",
    "validate_crs",
]
