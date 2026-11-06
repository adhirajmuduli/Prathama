"""Masked analysis grids: resolution, extent, cell centers, and limits.

A grid is always built inside a boundary in a projected CRS. The cell count is
checked against a hard ceiling before any array is allocated, so a too-fine
resolution fails loudly instead of exhausting memory.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import shapely
from shapely.geometry.base import BaseGeometry

from trendsmapp.constants import GRID_CELL_LIMITS
from trendsmapp.errors import ResourceLimitError, ValidationError
from trendsmapp.geospatial.crs import transformer_for, validate_crs

__all__ = [
    "GRID_CELL_LIMITS",
    "Grid",
    "build_grid",
]

#: (minimum, maximum) grid cells per frame, from the deployment ceilings.
# Re-exported from constants for convenience.


@dataclass(frozen=True, slots=True)
class Grid:
    """A regular masked grid in a projected CRS."""

    crs: str
    x_min: float
    y_min: float
    resolution_m: float
    n_cols: int
    n_rows: int
    #: (n_rows, n_cols) bool array: True where the cell center is inside the boundary.
    mask: np.ndarray

    @property
    def cell_count(self) -> int:
        """Return the total number of cells."""
        return self.n_cols * self.n_rows

    @property
    def masked_cell_count(self) -> int:
        """Return the number of cells inside the boundary."""
        return int(self.mask.sum())

    @property
    def x_centers(self) -> np.ndarray:
        """Return the x coordinate of every cell center, shape (n_cols,)."""
        return self.x_min + (np.arange(self.n_cols) + 0.5) * self.resolution_m

    @property
    def y_centers(self) -> np.ndarray:
        """Return the y coordinate of every cell center, shape (n_rows,)."""
        return self.y_min + (np.arange(self.n_rows) + 0.5) * self.resolution_m

    def cell_center_points(self) -> np.ndarray:
        """Return every cell center as an (N, 2) array of (x, y)."""
        x, y = np.meshgrid(self.x_centers, self.y_centers)
        return np.column_stack([x.ravel(), y.ravel()])

    def extent(self) -> tuple[float, float, float, float]:
        """Return the (x_min, y_min, x_max, y_max) extent of the grid."""
        return (
            self.x_min,
            self.y_min,
            self.x_min + self.n_cols * self.resolution_m,
            self.y_min + self.n_rows * self.resolution_m,
        )


def build_grid(
    boundary: BaseGeometry,
    *,
    resolution_m: float,
    crs: str,
    max_cells: int,
) -> Grid:
    """Build a masked grid covering the boundary at the given resolution.

    The boundary geometry is given in WGS84 and is projected into ``crs``
    (which must be projected) before the extent is computed, so resolutions
    are always metres per cell, never degrees. Cells whose center lies inside
    the projected boundary are masked in.
    """
    transformer = transformer_for("EPSG:4326", crs)
    target = validate_crs(crs)
    if target.is_geographic:
        raise ValidationError(
            "The grid CRS must be projected; degrees are not a grid unit.",
            details={"crs": crs, "reason": "geographic_grid_crs"},
        )
    if not isinstance(resolution_m, (int, float)) or resolution_m <= 0:
        raise ValidationError(
            "The grid resolution must be a positive number of metres.",
            details={"resolution_m": resolution_m},
        )
    low, high = GRID_CELL_LIMITS
    if not low <= max_cells <= high:
        raise ValidationError(
            "The maximum cell count is outside the accepted bounds.",
            details={"max_cells": max_cells, "bounds": [low, high]},
        )
    projected = shapely.transform(
        boundary,
        lambda coords: np.column_stack(
            transformer.transform(np.asarray(coords)[:, 0], np.asarray(coords)[:, 1])
        ),
    )
    minx, miny, maxx, maxy = projected.bounds
    n_cols = max(1, int(np.ceil((maxx - minx) / resolution_m)))
    n_rows = max(1, int(np.ceil((maxy - miny) / resolution_m)))
    cell_count = n_cols * n_rows
    if cell_count > max_cells:
        raise ResourceLimitError(
            "The grid would exceed the maximum cell count for one frame.",
            details={
                "cells": cell_count,
                "max_cells": max_cells,
                "resolution_m": resolution_m,
                "suggestion": "increase the resolution (metres per cell)",
            },
        )
    grid = Grid(
        crs=crs,
        x_min=float(minx),
        y_min=float(miny),
        resolution_m=float(resolution_m),
        n_cols=n_cols,
        n_rows=n_rows,
        mask=np.zeros((n_rows, n_cols), dtype=bool),
    )
    points = grid.cell_center_points()
    inside = shapely.contains_xy(projected, points[:, 0], points[:, 1])
    grid.mask.reshape(-1)[:] = inside
    return grid
