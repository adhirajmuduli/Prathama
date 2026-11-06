"""scikit-learn Gaussian-process adapter for small datasets.

A GP returns a predictive mean and standard deviation, so it is the
probabilistic alternative among the spatial methods. Its cost is cubic in the
number of observations, so the capability caps the point count and the pipeline
rejects a frame that exceeds it instead of stalling.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np

from trendsmapp.domain.enums import SpatialMethod
from trendsmapp.errors import ResourceLimitError, ValidationError
from trendsmapp.geospatial.distance import pairwise_distances
from trendsmapp.spatial.base import Prediction, SpatialMethodSpec

__all__ = ["MAX_GP_POINTS", "GPParams", "GaussianProcessInterpolator", "fit_gaussian_process"]

#: Maximum observations for a Gaussian process frame.
MAX_GP_POINTS: Final[int] = 2_000


@dataclass(frozen=True, slots=True)
class GPParams:
    """Validated Gaussian-process parameters."""

    length_scale_m: float = 5_000.0
    noise_variance: float = 1e-4

    def __post_init__(self) -> None:
        if self.length_scale_m <= 0:
            raise ValidationError(
                "The GP length scale must be positive.",
                details={"length_scale_m": self.length_scale_m},
            )
        if self.noise_variance < 0:
            raise ValidationError(
                "The GP noise variance must be non-negative.",
                details={"noise_variance": self.noise_variance},
            )


def _params_from(spec: SpatialMethodSpec) -> GPParams:
    """Build validated GP parameters from a recipe spec."""
    if spec.method is not SpatialMethod.GAUSSIAN_PROCESS:
        raise ValidationError(
            f"GP parameters cannot configure method '{spec.method.value}'.",
            details={"method": spec.method.value},
        )
    unknown = set(spec.params) - {"length_scale_m", "noise_variance"}
    if unknown:
        raise ValidationError(
            "Unknown GP parameters.",
            details={"unknown": sorted(unknown), "allowed": ["length_scale_m", "noise_variance"]},
        )
    return GPParams(
        length_scale_m=float(spec.params.get("length_scale_m", 5_000.0)),
        noise_variance=float(spec.params.get("noise_variance", 1e-4)),
    )


@dataclass(frozen=True, slots=True)
class GaussianProcessInterpolator:
    """A fitted Gaussian-process model."""

    points: np.ndarray
    values: np.ndarray
    params: GPParams
    crs: str
    _model: object

    @property
    def method(self) -> SpatialMethod:
        """Return the method of this interpolator."""
        return SpatialMethod.GAUSSIAN_PROCESS

    def predict(self, grid_points: np.ndarray) -> Prediction:
        """Predict at grid points, returning the predictive std as uncertainty."""
        from sklearn.gaussian_process import GaussianProcessRegressor

        grid_points = np.asarray(grid_points, dtype=float).reshape(-1, 2)
        model: GaussianProcessRegressor = self._model
        mean, std = model.predict(grid_points, return_std=True)
        support = pairwise_distances(grid_points, self.points, crs=self.crs).min(axis=1)
        return Prediction(
            values=np.asarray(mean, dtype=float).reshape(-1),
            uncertainty=np.maximum(np.asarray(std, dtype=float).reshape(-1), 0.0),
            support=support,
        )


def fit_gaussian_process(
    points: np.ndarray, values: np.ndarray, *, spec: SpatialMethodSpec, crs: str
) -> GaussianProcessInterpolator:
    """Fit a Gaussian process to observations in a projected CRS."""
    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.gaussian_process.kernels import RBF, WhiteKernel

    points = np.asarray(points, dtype=float).reshape(-1, 2)
    values = np.asarray(values, dtype=float).reshape(-1)
    if len(points) != len(values) or len(points) < 2:
        raise ValidationError(
            "A Gaussian process needs at least two observations.",
            details={"points": len(points)},
        )
    if len(points) > MAX_GP_POINTS:
        raise ResourceLimitError(
            "The frame exceeds the Gaussian-process point cap.",
            details={"points": len(points), "max_points": MAX_GP_POINTS},
        )
    params = _params_from(spec)
    kernel = RBF(length_scale=params.length_scale_m) + WhiteKernel(
        noise_level=params.noise_variance
    )
    model = GaussianProcessRegressor(kernel=kernel, normalize_y=True, random_state=0)
    model.fit(points, values)
    return GaussianProcessInterpolator(
        points=points, values=values, params=params, crs=crs, _model=model
    )
