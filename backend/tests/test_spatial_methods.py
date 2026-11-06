"""Scientific regression tests for the spatial methods, registry, validation, and rasters."""

from __future__ import annotations

import numpy as np
import pytest
import rasterio

from trendsmapp.domain.enums import SpatialMethod
from trendsmapp.errors import ResourceLimitError, ValidationError
from trendsmapp.geospatial.boundary import load_default_boundary
from trendsmapp.geospatial.grid import build_grid
from trendsmapp.spatial.base import SpatialMethodSpec, compute_metrics
from trendsmapp.spatial.gaussian_process import MAX_GP_POINTS, fit_gaussian_process
from trendsmapp.spatial.idw import fit_idw
from trendsmapp.spatial.kriging import fit_kriging
from trendsmapp.spatial.raster import write_geotiff, write_masked_png
from trendsmapp.spatial.rbf import fit_rbf
from trendsmapp.spatial.registry import (
    METHOD_REGISTRY,
    capability_for,
    fit_method,
    validate_methods,
)
from trendsmapp.spatial.uncertainty import normalize_uncertainty
from trendsmapp.spatial.validation import (
    leave_one_station_out,
    spatial_block_holdout,
    spatial_block_ids,
)

CRS = "EPSG:32644"


def _linear_field(points: np.ndarray) -> np.ndarray:
    """A known planar field: f(x, y) = 2x + 3y."""
    return 2.0 * points[:, 0] + 3.0 * points[:, 1]


def _sample_points() -> np.ndarray:
    rng = np.random.default_rng(42)
    return rng.uniform([960_000, 2_180_000], [975_000, 2_195_000], size=(12, 2))


def _spec(method: SpatialMethod, params: dict | None = None) -> SpatialMethodSpec:
    return SpatialMethodSpec(method=method, params=params or {})


class TestIDW:
    def test_exact_at_observations(self) -> None:
        points = _sample_points()
        values = _linear_field(points)
        fitted = fit_idw(points, values, spec=_spec(SpatialMethod.IDW), crs=CRS)
        prediction = fitted.predict(points)
        np.testing.assert_allclose(prediction.values, values, rtol=1e-9, atol=1e-9)
        assert prediction.uncertainty is None
        np.testing.assert_array_equal(prediction.support, np.zeros(len(points)))

    def test_interpolates_between_observations(self) -> None:
        points = _sample_points()
        values = _linear_field(points)
        fitted = fit_idw(points, values, spec=_spec(SpatialMethod.IDW, {"power": 1.0}), crs=CRS)
        midpoint = points.mean(axis=0, keepdims=True)
        predicted = fitted.predict(midpoint).values[0]
        expected = _linear_field(midpoint)[0]
        # IDW with power 1 on a linear field is close but not exact.
        assert abs(predicted - expected) / abs(expected) < 0.2

    def test_deterministic(self) -> None:
        points = _sample_points()
        values = _linear_field(points)
        grid = points[:5]
        first = fit_idw(points, values, spec=_spec(SpatialMethod.IDW), crs=CRS).predict(grid)
        second = fit_idw(points, values, spec=_spec(SpatialMethod.IDW), crs=CRS).predict(grid)
        np.testing.assert_array_equal(first.values, second.values)
        np.testing.assert_array_equal(first.support, second.support)

    def test_distance_floor_handles_coincident_points(self) -> None:
        points = np.array([[1000.0, 1000.0], [1000.0, 1000.0], [2000.0, 2000.0]])
        values = np.array([1.0, 3.0, 5.0])
        fitted = fit_idw(
            points, values, spec=_spec(SpatialMethod.IDW, {"distance_floor_m": 10.0}), crs=CRS
        )
        prediction = fitted.predict(np.array([[1000.0, 1000.0]]))
        assert np.isfinite(prediction.values[0])
        assert prediction.values[0] == pytest.approx(2.0, abs=0.01)

    def test_neighbor_limit(self) -> None:
        points = _sample_points()
        values = _linear_field(points)
        fitted = fit_idw(
            points, values, spec=_spec(SpatialMethod.IDW, {"max_neighbors": 3}), crs=CRS
        )
        prediction = fitted.predict(points[:4])
        assert prediction.values.shape == (4,)
        assert np.all(np.isfinite(prediction.values))

    def test_rejects_non_finite_values(self) -> None:
        points = _sample_points()
        values = _linear_field(points)
        values[0] = float("nan")
        with pytest.raises(ResourceLimitError):
            fit_idw(points, values, spec=_spec(SpatialMethod.IDW), crs=CRS)

    def test_rejects_bad_params(self) -> None:
        points = _sample_points()
        values = _linear_field(points)
        with pytest.raises(ValidationError):
            fit_idw(points, values, spec=_spec(SpatialMethod.IDW, {"power": 0}), crs=CRS)
        with pytest.raises(ValidationError):
            fit_idw(points, values, spec=_spec(SpatialMethod.IDW, {"unknown_param": 1}), crs=CRS)


class TestRBF:
    def test_interpolates_at_observations(self) -> None:
        points = _sample_points()
        values = np.sin(points[:, 0] / 1000.0) + np.cos(points[:, 1] / 1000.0)
        fitted = fit_rbf(points, values, spec=_spec(SpatialMethod.RBF), crs=CRS)
        prediction = fitted.predict(points)
        np.testing.assert_allclose(prediction.values, values, rtol=1e-3, atol=1e-3)

    def test_rejects_bad_kernel(self) -> None:
        points = _sample_points()
        values = _linear_field(points)
        with pytest.raises(ValidationError):
            fit_rbf(points, values, spec=_spec(SpatialMethod.RBF, {"kernel": "nope"}), crs=CRS)


class TestKriging:
    def test_predicts_with_variance(self) -> None:
        points = _sample_points()
        values = _linear_field(points)
        fitted = fit_kriging(points, values, spec=_spec(SpatialMethod.KRIGING), crs=CRS)
        prediction = fitted.predict(points[:6])
        assert prediction.values.shape == (6,)
        assert prediction.uncertainty is not None
        assert np.all(prediction.uncertainty >= 0)
        np.testing.assert_allclose(
            prediction.values, values[:6], rtol=0.2, atol=abs(values[:6].mean()) * 0.2 + 1.0
        )


class TestGaussianProcess:
    def test_predicts_mean_and_std(self) -> None:
        points = _sample_points()[:8]
        values = _linear_field(points)
        fitted = fit_gaussian_process(
            points, values, spec=_spec(SpatialMethod.GAUSSIAN_PROCESS), crs=CRS
        )
        prediction = fitted.predict(points)
        assert prediction.uncertainty is not None
        assert np.all(prediction.uncertainty >= 0)
        np.testing.assert_allclose(prediction.values, values, rtol=0.1, atol=10.0)

    def test_point_cap(self) -> None:
        points = np.zeros((MAX_GP_POINTS + 1, 2))
        values = np.zeros(MAX_GP_POINTS + 1)
        with pytest.raises(ResourceLimitError):
            fit_gaussian_process(
                points, values, spec=_spec(SpatialMethod.GAUSSIAN_PROCESS), crs=CRS
            )


class TestRegistry:
    def test_all_methods_registered(self) -> None:
        assert set(METHOD_REGISTRY) == set(SpatialMethod)
        for method in SpatialMethod:
            assert capability_for(method).method is method

    def test_unknown_method_rejected(self) -> None:
        with pytest.raises(ValidationError):
            validate_methods([SpatialMethodSpec(method="not_a_method")])  # type: ignore[arg-type]

    def test_duplicate_methods_rejected(self) -> None:
        with pytest.raises(ValidationError):
            validate_methods([_spec(SpatialMethod.IDW), _spec(SpatialMethod.IDW, {"power": 3})])

    def test_fit_method_dispatches(self) -> None:
        points = _sample_points()
        values = _linear_field(points)
        fitted = fit_method(_spec(SpatialMethod.IDW), points, values, crs=CRS)
        assert fitted.method is SpatialMethod.IDW


class TestValidation:
    def test_loso_with_exact_interpolator_scores_perfectly(self) -> None:
        points = _sample_points()
        values = _linear_field(points)
        stations = [f"st{i % 4}" for i in range(len(points))]

        def exact_fit_predict(
            train_points: np.ndarray, train_values: np.ndarray, test_points: np.ndarray
        ) -> np.ndarray:
            return _linear_field(test_points)

        metrics = leave_one_station_out(
            points,
            values,
            stations,
            spec=_spec(SpatialMethod.IDW),
            crs=CRS,
            fit_predict=exact_fit_predict,
        )
        assert metrics.fold_count == 4
        assert metrics.rmse == pytest.approx(0.0, abs=1e-9)
        assert metrics.valid_count == len(points)

    def test_spatial_blocks_are_deterministic(self) -> None:
        points = _sample_points()
        first = spatial_block_ids(points, block_size_m=5000.0)
        second = spatial_block_ids(points, block_size_m=5000.0)
        assert first == second
        assert len(set(first)) >= 1

    def test_spatial_block_holdout_runs(self) -> None:
        points = _sample_points()
        values = _linear_field(points)

        def nearest_predict(
            train_points: np.ndarray, train_values: np.ndarray, test_points: np.ndarray
        ) -> np.ndarray:
            from trendsmapp.geospatial.distance import pairwise_distances

            distances = pairwise_distances(test_points, train_points, crs=CRS)
            nearest = distances.argmin(axis=1)
            return train_values[nearest]

        metrics = spatial_block_holdout(
            points, values, spec=_spec(SpatialMethod.IDW), crs=CRS, fit_predict=nearest_predict
        )
        assert metrics.fold_count >= 1
        assert metrics.valid_count == len(points)

    def test_compute_metrics(self) -> None:
        metrics = compute_metrics(np.array([1.0, -1.0, 2.0]))
        assert metrics.mae == pytest.approx(4 / 3)
        assert metrics.rmse == pytest.approx(np.sqrt(2.0))
        assert metrics.bias == pytest.approx(2 / 3)
        assert metrics.valid_count == 3


class TestUncertainty:
    def test_kriging_payload_has_native_uncertainty(self) -> None:
        payload = normalize_uncertainty(
            SpatialMethod.KRIGING,
            raw_uncertainty=np.array([1.0, 4.0]),
            support_m=np.array([10.0, 20.0]),
        )
        assert payload.kind == "kriging_std"
        np.testing.assert_array_equal(payload.values, np.array([1.0, 4.0]))

    def test_idw_payload_is_support_only(self) -> None:
        payload = normalize_uncertainty(
            SpatialMethod.IDW, raw_uncertainty=np.array([1.0]), support_m=np.array([10.0])
        )
        assert payload.kind == "support_only"
        assert payload.values is None


class TestRaster:
    def test_geotiff_round_trips_with_crs_and_nodata(self) -> None:
        boundary = load_default_boundary()
        grid = build_grid(boundary.geometry, resolution_m=5_000.0, crs=CRS, max_cells=250_000)
        assert grid.masked_cell_count > 0
        values = np.full((grid.n_rows, grid.n_cols), 6.8)
        result = write_geotiff(values, grid)
        assert result.sha256 == result.sha256
        import io

        with rasterio.open(io.BytesIO(result.payload)) as dataset:
            assert dataset.crs.to_string() == CRS
            assert dataset.width == grid.n_cols
            assert dataset.height == grid.n_rows
            data = dataset.read(1)
            inside = grid.mask
            assert np.allclose(data[inside], 6.8)
            assert np.all(data[~inside] == -9999.0)

    def test_png_is_a_masked_image(self) -> None:
        boundary = load_default_boundary()
        grid = build_grid(boundary.geometry, resolution_m=5_000.0, crs=CRS, max_cells=250_000)
        values = np.full((grid.n_rows, grid.n_cols), 6.8)
        result = write_masked_png(values, grid)
        assert result.payload[:8] == b"\x89PNG\r\n\x1a\n"
        assert result.size_bytes == len(result.payload)
