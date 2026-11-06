"""SciPy RBFInterpolator adapter with explicit kernel, smoothing, and neighbors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np
from scipy.interpolate import RBFInterpolator

from trendsmapp.domain.enums import SpatialMethod
from trendsmapp.errors import ValidationError
from trendsmapp.geospatial.distance import pairwise_distances
from trendsmapp.spatial.base import Prediction, SpatialMethodSpec

__all__ = ["RBFParams", "RbfInterpolator", "fit_rbf"]

#: Kernels RBFInterpolator supports.
ALLOWED_KERNELS: Final[tuple[str, ...]] = (
    "thin_plate_spline",
    "linear",
    "cubic",
    "quintic",
    "multiquadric",
    "inverse_multiquadric",
    "inverse_quadratic",
    "gaussian",
)

DEFAULT_KERNEL: Final[str] = "thin_plate_spline"


@dataclass(frozen=True, slots=True)
class RBFParams:
    """Validated RBF parameters."""

    kernel: str = DEFAULT_KERNEL
    smoothing: float = 0.0
    epsilon: float | None = None
    max_neighbors: int | None = None

    def __post_init__(self) -> None:
        if self.kernel not in ALLOWED_KERNELS:
            raise ValidationError(
                "The RBF kernel is not supported.",
                details={"kernel": self.kernel, "allowed": list(ALLOWED_KERNELS)},
            )
        if self.smoothing < 0:
            raise ValidationError(
                "The RBF smoothing must be non-negative.", details={"smoothing": self.smoothing}
            )
        if self.epsilon is not None and self.epsilon <= 0:
            raise ValidationError(
                "The RBF epsilon must be positive.", details={"epsilon": self.epsilon}
            )
        if self.max_neighbors is not None and self.max_neighbors < 3:
            raise ValidationError(
                "RBF needs at least three neighbors.", details={"max_neighbors": self.max_neighbors}
            )


def _params_from(spec: SpatialMethodSpec) -> RBFParams:
    """Build validated RBF parameters from a recipe spec."""
    if spec.method is not SpatialMethod.RBF:
        raise ValidationError(
            f"RBF parameters cannot configure method '{spec.method.value}'.",
            details={"method": spec.method.value},
        )
    unknown = set(spec.params) - {"kernel", "smoothing", "epsilon", "max_neighbors"}
    if unknown:
        raise ValidationError(
            "Unknown RBF parameters.",
            details={
                "unknown": sorted(unknown),
                "allowed": ["kernel", "smoothing", "epsilon", "max_neighbors"],
            },
        )
    epsilon = spec.params.get("epsilon")
    return RBFParams(
        kernel=str(spec.params.get("kernel", DEFAULT_KERNEL)),
        smoothing=float(spec.params.get("smoothing", 0.0)),
        epsilon=float(epsilon) if epsilon is not None else None,
        max_neighbors=(
            int(spec.params["max_neighbors"])
            if spec.params.get("max_neighbors") is not None
            else None
        ),
    )


@dataclass(frozen=True, slots=True)
class RbfInterpolator:
    """A fitted RBF model."""

    points: np.ndarray
    values: np.ndarray
    params: RBFParams
    crs: str
    _model: RBFInterpolator

    @property
    def method(self) -> SpatialMethod:
        """Return the method of this interpolator."""
        return SpatialMethod.RBF

    def predict(self, grid_points: np.ndarray) -> Prediction:
        """Predict at grid points in the same CRS as the fit points."""
        grid_points = np.asarray(grid_points, dtype=float).reshape(-1, 2)
        values = np.asarray(self._model(grid_points), dtype=float)
        support = pairwise_distances(grid_points, self.points, crs=self.crs).min(axis=1)
        return Prediction(values=values, uncertainty=None, support=support)


def fit_rbf(
    points: np.ndarray, values: np.ndarray, *, spec: SpatialMethodSpec, crs: str
) -> RbfInterpolator:
    """Fit an RBF model to observations in a projected CRS."""
    points = np.asarray(points, dtype=float).reshape(-1, 2)
    values = np.asarray(values, dtype=float).reshape(-1)
    if len(points) != len(values) or len(points) < 3:
        raise ValidationError(
            "RBF needs at least three observations.",
            details={"points": len(points)},
        )
    params = _params_from(spec)
    kwargs: dict[str, object] = {"kernel": params.kernel, "smoothing": params.smoothing}
    if params.epsilon is not None:
        kwargs["epsilon"] = params.epsilon
    if params.max_neighbors is not None:
        kwargs["neighbors"] = params.max_neighbors
    model = RBFInterpolator(points, values, **kwargs)
    return RbfInterpolator(points=points, values=values, params=params, crs=crs, _model=model)
