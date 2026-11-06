"""Raster outputs: GeoTIFF, masked PNG, extent metadata, and checksums.

Rasters are written from in-memory arrays so nothing touches a user path. The
GeoTIFF carries the projected CRS and the extent; the PNG is masked so
outside-lagoon cells stay transparent. Both return their bytes and SHA-256.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from typing import Final

import numpy as np

from trendsmapp.geospatial.grid import Grid
from trendsmapp.geospatial.masking import NODATA, masked_array

__all__ = [
    "RasterWriteResult",
    "write_geotiff",
    "write_masked_png",
]

#: Default matplotlib colormap for concentration-like surfaces.
DEFAULT_COLORMAP: Final[str] = "viridis"


@dataclass(frozen=True, slots=True)
class RasterWriteResult:
    """The bytes and digest of a written raster."""

    payload: bytes
    sha256: str
    size_bytes: int


def grid_from_geotiff(payload: bytes) -> tuple[Grid, np.ndarray]:
    """Reconstruct the grid and values from a written GeoTIFF payload.

    The grid is rebuilt from the extent tags written at creation; the mask is
    recovered from the nodata cells, so a stored raster is fully
    self-describing.
    """
    import io

    import rasterio

    with rasterio.open(io.BytesIO(payload)) as dataset:
        data = dataset.read(1)
        tags = dict(dataset.tags().items())
        transform = dataset.transform
        crs = dataset.crs.to_string()
    n_rows, n_cols = data.shape
    resolution = float(transform.a)
    x_min = float(transform.c)
    y_max = float(transform.f)
    y_min = y_max - n_rows * resolution
    nodata = float(tags.get("nodata", str(NODATA)))
    values = np.asarray(data, dtype=float)
    values[data == nodata] = np.nan  # nodata cells are excluded from scales and statistics
    mask = data != nodata
    grid = Grid(
        crs=crs,
        x_min=x_min,
        y_min=y_min,
        resolution_m=resolution,
        n_cols=n_cols,
        n_rows=n_rows,
        mask=mask,
    )
    return grid, values


def _extent_metadata(grid: Grid) -> dict[str, object]:
    """Return the exact extent metadata of a grid."""
    x_min, y_min, x_max, y_max = grid.extent()
    return {
        "crs": grid.crs,
        "x_min": x_min,
        "y_min": y_min,
        "x_max": x_max,
        "y_max": y_max,
        "n_cols": grid.n_cols,
        "n_rows": grid.n_rows,
        "resolution_m": grid.resolution_m,
        "nodata": NODATA,
    }


def write_geotiff(values: np.ndarray, grid: Grid) -> RasterWriteResult:
    """Write a single-band float32 GeoTIFF of ``values`` on ``grid``."""
    from rasterio.io import MemoryFile
    from rasterio.transform import from_origin

    masked = masked_array(values, grid)
    data = np.asarray(masked.filled(NODATA), dtype=np.float32)
    x_min, _y_min, _x_max, y_max = grid.extent()
    transform = from_origin(x_min, y_max, grid.resolution_m, grid.resolution_m)
    buffer = io.BytesIO()
    with MemoryFile() as memory:
        with memory.open(
            driver="GTiff",
            height=grid.n_rows,
            width=grid.n_cols,
            count=1,
            dtype="float32",
            crs=grid.crs,
            transform=transform,
            nodata=NODATA,
        ) as dataset:
            dataset.write(data, 1)
            dataset.update_tags(**{str(k): str(v) for k, v in _extent_metadata(grid).items()})
        buffer.write(memory.read())
    payload = buffer.getvalue()
    return RasterWriteResult(
        payload=payload,
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
    )


def write_masked_png(
    values: np.ndarray,
    grid: Grid,
    *,
    vmin: float | None = None,
    vmax: float | None = None,
    cmap: str = DEFAULT_COLORMAP,
) -> RasterWriteResult:
    """Write a masked PNG of ``values`` on ``grid`` for the frontend overlay."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    masked = masked_array(values, grid)
    finite = masked.compressed()
    if vmin is None:
        vmin = float(np.nanmin(finite)) if finite.size else 0.0
    if vmax is None:
        vmax = float(np.nanmax(finite)) if finite.size else 1.0
    if vmax <= vmin:
        vmax = vmin + 1.0
    figure, axis = plt.subplots(figsize=(grid.n_cols / 100, grid.n_rows / 100), dpi=100)
    image = axis.imshow(masked, cmap=cmap, vmin=vmin, vmax=vmax, origin="upper")
    axis.set_axis_off()
    figure.colorbar(image, ax=axis, shrink=0.6)
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png", bbox_inches="tight", pad_inches=0, transparent=True)
    plt.close(figure)
    payload = buffer.getvalue()
    return RasterWriteResult(
        payload=payload,
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
    )
