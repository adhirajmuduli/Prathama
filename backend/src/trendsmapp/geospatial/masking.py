"""Vectorized lagoon masking and raster nodata application."""

from __future__ import annotations

import numpy as np

from trendsmapp.geospatial.grid import Grid

__all__ = ["apply_nodata", "lagoon_mask", "masked_array"]

#: The nodata value used in written rasters.
NODATA: float = -9999.0


def lagoon_mask(grid: Grid) -> np.ndarray:
    """Return the boolean inside-boundary mask of a grid."""
    return grid.mask


def apply_nodata(values: np.ndarray, grid: Grid, *, nodata: float = NODATA) -> np.ndarray:
    """Return a copy of ``values`` with cells outside the boundary set to nodata."""
    result = np.array(values, dtype=float, copy=True)
    if result.shape != grid.mask.shape:
        raise ValueError(
            f"values shape {result.shape} does not match the grid mask {grid.mask.shape}"
        )
    result[~grid.mask] = nodata
    return result


def masked_array(values: np.ndarray, grid: Grid, *, nodata: float = NODATA) -> np.ma.MaskedArray:
    """Return ``values`` as a masked array with outside cells masked."""
    return np.ma.masked_array(values, mask=~grid.mask, fill_value=nodata)
