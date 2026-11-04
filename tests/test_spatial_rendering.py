import json

import numpy as np
import shapely

from utils.spatial_rendering import interpolate_surface, load_boundary, render_surface_png


def _boundary(tmp_path):
    boundary_path = tmp_path / "boundary.geojson"
    boundary_path.write_text(json.dumps({
        "type": "Polygon",
        "coordinates": [[[85.0, 19.4], [85.3, 19.4], [85.3, 19.7], [85.0, 19.7], [85.0, 19.4]]],
    }), encoding="utf-8")
    return load_boundary(boundary_path)[0]


def test_idw_surface_is_masked_renderable_and_bounded(tmp_path):
    surface, extent, mask = interpolate_surface(
        np.array([85.05, 85.25, 85.05, 85.25]),
        np.array([19.45, 19.45, 19.65, 19.65]),
        np.array([1.0, 2.0, 3.0, 4.0]),
        _boundary(tmp_path),
        resolution=60,
    )
    assert surface.shape == (60, 60)
    assert mask.any() and (~mask).any()
    assert np.nanmin(surface) >= 1.0
    assert np.nanmax(surface) <= 4.0
    assert render_surface_png(surface, extent, 1.0, 4.0, "viridis").startswith(b"\x89PNG")


def test_dense_high_value_cluster_produces_high_local_idw_values(tmp_path):
    rng = np.random.default_rng(42)
    high_longitude = 85.08 + rng.normal(0, 0.002, 100)
    high_latitude = 19.48 + rng.normal(0, 0.002, 100)
    longitude = np.concatenate([high_longitude, [85.25, 85.25, 85.24]])
    latitude = np.concatenate([high_latitude, [19.65, 19.64, 19.65]])
    values = np.concatenate([np.full(100, 90.0), [10.0, 10.0, 10.0]])
    surface, extent, _ = interpolate_surface(longitude, latitude, values, _boundary(tmp_path), resolution=100)
    min_lon, max_lon, min_lat, max_lat = extent
    high_x = round((85.08 - min_lon) / (max_lon - min_lon) * 99)
    high_y = round((19.48 - min_lat) / (max_lat - min_lat) * 99)
    low_x = round((85.25 - min_lon) / (max_lon - min_lon) * 99)
    low_y = round((19.65 - min_lat) / (max_lat - min_lat) * 99)
    assert surface[high_y, high_x] > 80
    assert surface[low_y, low_x] < 25


def test_idw_exact_station_match_uses_colocated_mean(tmp_path):
    surface, _, _ = interpolate_surface(
        np.array([85.05, 85.05, 85.25]),
        np.array([19.45, 19.45, 19.65]),
        np.array([1.0, 3.0, 10.0]),
        _boundary(tmp_path),
        resolution=61,
    )
    assert surface[10, 10] == 2.0


def test_kde_kernel_mean_is_masked_bounded_and_bandwidth_sensitive(tmp_path):
    longitude = np.array([85.05, 85.08, 85.25])
    latitude = np.array([19.45, 19.48, 19.65])
    values = np.array([10.0, 10.0, 90.0])
    narrow, _, mask = interpolate_surface(
        longitude, latitude, values, _boundary(tmp_path), method="kde", resolution=61, bandwidth_km=1.0
    )
    broad, _, _ = interpolate_surface(
        longitude, latitude, values, _boundary(tmp_path), method="kde", resolution=61, bandwidth_km=30.0
    )
    assert np.nanmin(narrow) >= 10.0 - 1e-12
    assert np.nanmax(narrow) <= 90.0 + 1e-12
    assert np.isnan(narrow[~mask]).all()
    assert np.nanstd(broad) < np.nanstd(narrow)


def test_boundaries_are_prepared_for_fast_masking(tmp_path):
    boundary_path = tmp_path / "prepared_boundary.geojson"
    boundary_path.write_text(json.dumps({
        "type": "Polygon",
        "coordinates": [[[85.0, 19.4], [85.3, 19.4], [85.3, 19.7], [85.0, 19.7], [85.0, 19.4]]],
    }), encoding="utf-8")
    loaded = load_boundary(boundary_path)[0]
    assert shapely.is_prepared(loaded)

    # interpolate_surface must prepare raw geometries itself; both paths agree exactly.
    def surface_from(raw_geometry):
        return interpolate_surface(
            np.array([85.05, 85.25, 85.05, 85.25]),
            np.array([19.45, 19.45, 19.65, 19.65]),
            np.array([1.0, 2.0, 3.0, 4.0]),
            raw_geometry,
            resolution=60,
        )

    unprepared_first = shapely.from_geojson(boundary_path.read_text())
    assert not shapely.is_prepared(unprepared_first)
    surface_a, extent_a, mask_a = surface_from(unprepared_first)
    surface_b, extent_b, mask_b = surface_from(load_boundary(boundary_path)[0])
    assert np.array_equal(mask_a, mask_b)
    assert np.allclose(surface_a, surface_b, equal_nan=True)
