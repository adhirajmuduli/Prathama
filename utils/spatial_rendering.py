from __future__ import annotations

import io
import json
import math
import threading
from pathlib import Path

import matplotlib
import numpy as np
import shapely
from shapely.geometry import shape

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colorbar import ColorbarBase
from matplotlib.colors import Normalize

_MATPLOTLIB_LOCK = threading.Lock()


def ensure_prepared(boundary):
    """Return the boundary with its GEOS preparation flag set.

    shapely's vectorized ``contains_xy`` does not prepare geometries
    automatically; against a detailed coastline (10k+ vertices) every grid-cell
    test then costs O(vertices), which made surface generation ~1900x slower
    than necessary. Preparation is idempotent and changes no results.
    """
    if not shapely.is_prepared(boundary):
        shapely.prepare(boundary)
    return boundary


def _count_vertices(geometry) -> int:
    """Count total vertices in a geometry (exterior + interiors for all polygons)."""
    if geometry.geom_type == "Polygon":
        polygons = [geometry]
    else:  # MultiPolygon
        polygons = list(geometry.geoms)
    return sum(len(poly.exterior.coords) + sum(len(interior.coords) for interior in poly.interiors)
               for poly in polygons)


class SpatialRenderingError(ValueError):
    """Raised when a spatial surface cannot be generated safely."""


def load_boundary(path: str | Path):
    with Path(path).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if payload.get("type") == "FeatureCollection":
        features = payload.get("features") or []
        if len(features) != 1:
            raise SpatialRenderingError("Boundary GeoJSON must contain exactly one feature.")
        geometry = features[0].get("geometry")
    elif payload.get("type") == "Feature":
        geometry = payload.get("geometry")
    else:
        geometry = payload
    boundary = shape(geometry)
    if boundary.geom_type not in {"Polygon", "MultiPolygon"} or boundary.is_empty:
        raise SpatialRenderingError("Boundary must be a non-empty Polygon or MultiPolygon.")
    if not boundary.is_valid:
        repaired = boundary.buffer(0)
        if repaired.is_empty or not repaired.is_valid:
            raise SpatialRenderingError("Boundary geometry is invalid and could not be repaired.")
        boundary = repaired
        repair_info = {
            "repaired": True,
            "original_vertices": _count_vertices(boundary),
            "repaired_vertices": _count_vertices(repaired),
            "area_delta": abs(repaired.area - boundary.area)
        }
    else:
        repair_info = {"repaired": False}
    return ensure_prepared(boundary), repair_info


def _project_km(longitude: np.ndarray, latitude: np.ndarray, reference_latitude: float) -> np.ndarray:
    x = longitude * (111.320 * math.cos(math.radians(reference_latitude)))
    y = latitude * 110.574
    return np.column_stack((x, y))


def interpolate_surface(
    longitude: np.ndarray,
    latitude: np.ndarray,
    values: np.ndarray,
    boundary,
    method: str = "idw",
    resolution: int = 220,
    power: float = 2.0,
    bandwidth_km: float = 2.0,
) -> tuple[np.ndarray, tuple[float, float, float, float], np.ndarray]:
    if len(values) < 1:
        raise SpatialRenderingError("At least one observation is required.")
    if resolution < 50 or resolution > 500:
        raise SpatialRenderingError("Grid resolution must be between 50 and 500.")
    if not np.isfinite(power) or power <= 0:
        raise SpatialRenderingError("IDW power must be a positive finite value.")
    if not np.isfinite(bandwidth_km) or bandwidth_km <= 0:
        raise SpatialRenderingError("KDE bandwidth must be a positive finite kilometre value.")

    min_lon, min_lat, max_lon, max_lat = boundary.bounds
    ensure_prepared(boundary)
    grid_lon = np.linspace(min_lon, max_lon, resolution)
    grid_lat = np.linspace(min_lat, max_lat, resolution)
    grid_x, grid_y = np.meshgrid(grid_lon, grid_lat)
    reference_latitude = (min_lat + max_lat) / 2
    observations = _project_km(longitude, latitude, reference_latitude)
    targets = _project_km(grid_x.ravel(), grid_y.ravel(), reference_latitude)

    unique, inverse = np.unique(observations, axis=0, return_inverse=True)
    aggregated = np.array([values[inverse == index].mean() for index in range(len(unique))])
    normalized_method = method.lower()
    if normalized_method == "idw":
        predicted = np.empty(len(targets), dtype=float)
        chunk_size = max(100, min(10_000, 2_000_000 // len(unique)))
        for start in range(0, len(targets), chunk_size):
            chunk = targets[start : start + chunk_size]
            distances = np.linalg.norm(chunk[:, None, :] - unique[None, :, :], axis=2)
            exact = distances <= 1e-9
            weights = 1.0 / np.maximum(distances, 1e-9) ** power
            chunk_values = (weights @ aggregated) / weights.sum(axis=1)
            exact_rows = exact.any(axis=1)
            if exact_rows.any():
                chunk_values[exact_rows] = aggregated[exact[exact_rows].argmax(axis=1)]
            predicted[start : start + len(chunk)] = chunk_values
    elif normalized_method == "kde":
        predicted = np.empty(len(targets), dtype=float)
        chunk_size = max(100, min(10_000, 2_000_000 // len(unique)))
        for start in range(0, len(targets), chunk_size):
            chunk = targets[start : start + chunk_size]
            squared_distances = np.sum((chunk[:, None, :] - unique[None, :, :]) ** 2, axis=2)
            weights = np.exp(-0.5 * squared_distances / bandwidth_km**2)
            denominators = weights.sum(axis=1)
            nearest = squared_distances.argmin(axis=1)
            chunk_values = np.divide(
                weights @ aggregated,
                denominators,
                out=aggregated[nearest].copy(),
                where=denominators > np.finfo(float).tiny,
            )
            predicted[start : start + len(chunk)] = chunk_values
    else:
        raise SpatialRenderingError(f"Unsupported interpolation method: {method}")

    try:
        from shapely import contains_xy

        mask = contains_xy(boundary, grid_x, grid_y)
    except ImportError:
        from shapely.geometry import Point

        mask = np.fromiter(
            (boundary.covers(Point(x, y)) for x, y in zip(grid_x.ravel(), grid_y.ravel(), strict=True)),
            dtype=bool,
        ).reshape(grid_x.shape)
    surface = predicted.reshape(grid_x.shape)
    surface[~mask] = np.nan
    return surface, (min_lon, max_lon, min_lat, max_lat), mask


def render_surface_png(
    surface: np.ndarray,
    extent: tuple[float, float, float, float],
    minimum: float,
    maximum: float,
    colormap: str,
    label: str | None = None,
) -> bytes:
    if not np.isfinite(minimum) or not np.isfinite(maximum) or minimum > maximum:
        raise SpatialRenderingError("The global visualization range is invalid.")
    if minimum == maximum:
        maximum = minimum + 1e-9
    try:
        matplotlib.colormaps[colormap]
    except KeyError as exc:
        raise SpatialRenderingError(f"Unknown colormap: {colormap}") from exc

    min_lon, max_lon, min_lat, max_lat = extent
    aspect = max((max_lon - min_lon) / max(max_lat - min_lat, 1e-9), 0.25)
    with _MATPLOTLIB_LOCK:
        figure, axis = plt.subplots(figsize=(6, 6 / aspect), dpi=120)
        figure.patch.set_alpha(0)
        axis.patch.set_alpha(0)
        axis.imshow(
            surface,
            cmap=colormap,
            origin="lower",
            extent=extent,
            interpolation="bilinear",
            vmin=minimum,
            vmax=maximum,
        )
        if label:
            axis.text(
                0.02,
                0.02,
                label,
                transform=axis.transAxes,
                color="white",
                fontsize=9,
                bbox={"facecolor": "black", "alpha": 0.65, "pad": 3},
            )
        axis.set_xlim(min_lon, max_lon)
        axis.set_ylim(min_lat, max_lat)
        axis.set_aspect("equal", adjustable="box")
        axis.axis("off")
        figure.subplots_adjust(left=0, right=1, top=1, bottom=0)
        output = io.BytesIO()
        figure.savefig(output, format="png", transparent=True, bbox_inches=None, pad_inches=0)
        plt.close(figure)
    return output.getvalue()


def render_colorbar_png(minimum: float, maximum: float, colormap: str, horizontal: bool = False) -> bytes:
    """Render a colorbar legend PNG for the requested value range and orientation."""
    if not np.isfinite(minimum) or not np.isfinite(maximum) or minimum > maximum:
        raise SpatialRenderingError("The global visualization range is invalid.")
    try:
        matplotlib.colormaps[colormap]
    except KeyError as exc:
        raise SpatialRenderingError(f"Unknown colormap: {colormap}") from exc

    with _MATPLOTLIB_LOCK:
        if horizontal:
            figure, axis = plt.subplots(figsize=(6, 1.2))
            orientation = "horizontal"
        else:
            figure, axis = plt.subplots(figsize=(1.2, 6))
            orientation = "vertical"
        colormap_object = matplotlib.colormaps[colormap]
        ColorbarBase(axis, cmap=colormap_object, norm=Normalize(minimum, maximum), orientation=orientation)
        output = io.BytesIO()
        figure.savefig(output, format="png", dpi=140, bbox_inches="tight", transparent=True, pad_inches=0.15)
        plt.close(figure)
    return output.getvalue()
