"""Heatmap rendering from raster outputs: PNG for the frontend overlay."""

from __future__ import annotations

import numpy as np

from trendsmapp.geospatial.grid import Grid
from trendsmapp.spatial.raster import RasterWriteResult, write_masked_png
from trendsmapp.visualization.palettes import PaletteSpec, resolve_palette
from trendsmapp.visualization.scales import ScaleResult

__all__ = ["render_heatmap_png"]


def render_heatmap_png(
    values: np.ndarray,
    grid: Grid,
    *,
    scale: ScaleResult,
    palette: PaletteSpec | str = "viridis",
) -> RasterWriteResult:
    """Render one masked heatmap PNG under the given scale and palette."""
    palette_spec = palette if isinstance(palette, PaletteSpec) else resolve_palette(palette)
    return write_masked_png(values, grid, vmin=scale.vmin, vmax=scale.vmax, cmap=palette_spec.cmap)
