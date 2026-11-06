"""PyKrige ordinary-kriging adapter with variogram configuration.

Kriging provides a variogram-based prediction and a kriging variance, which is
the method's native uncertainty. It is used only when the recipe selects it;
its outputs are kept separate from other methods.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np

from trendsmapp.domain.enums import SpatialMethod
from trendsmapp.errors import ValidationError
from trendsmapp.geospatial.distance import pairwise_distances
from trendsmapp.spatial.base import Prediction, SpatialMethodSpec

__all__ = ["KrigingInterpolator", "KrigingParams", "fit_kriging"]

#: Variogram models PyKrige supports.
ALLOWED_VARIOGRAM_MODELS: Final[tuple[str, ...]] = (
    "linear",
    "power",
    "gaussian",
    "spherical",
    "exponential",
)

DEFAULT_VARIOGRAM_MODEL: Final[str] = "spherical"


@dataclass(frozen=True, slots=True)
class KrigingParams:
    """Validated kriging parameters."""

    variogram_model: str = DEFAULT_VARIOGRAM_MODEL
    nlags: int = 6
    anisotropy_scaling: float = 1.0

    def __post_init__(self) -> None:
        if self.variogram_model not in ALLOWED_VARIOGRAM_MODELS:
            raise ValidationError(
                "The variogram model is not supported.",
                details={
                    "variogram_model": self.variogram_model,
                    "allowed": list(ALLOWED_VARIOGRAM_MODELS),
                },
            )
        if self.nlags < 2:
            raise ValidationError(
                "Kriging needs at least two variogram lags.", details={"nlags": self.nlags}
            )
        if self.anisotropy_scaling <= 0:
            raise ValidationError(
                "The anisotropy scaling must be positive.",
                details={"anisotropy_scaling": self.anisotropy_scaling},
            )


def _params_from(spec: SpatialMethodSpec) -> KrigingParams:
    """Build validated kriging parameters from a recipe spec."""
    if spec.method is not SpatialMethod.KRIGING:
        raise ValidationError(
            f"Kriging parameters cannot configure method '{spec.method.value}'.",
            details={"method": spec.method.value},
        )
    unknown = set(spec.params) - {"variogram_model", "nlags", "anisotropy_scaling"}
    if unknown:
        raise ValidationError(
            "Unknown kriging parameters.",
            details={
                "unknown": sorted(unknown),
                "allowed": ["variogram_model", "nlags", "anisotropy_scaling"],
            },
        )
    return KrigingParams(
        variogram_model=str(spec.params.get("variogram_model", DEFAULT_VARIOGRAM_MODEL)),
        nlags=int(spec.params.get("nlags", 6)),
        anisotropy_scaling=float(spec.params.get("anisotropy_scaling", 1.0)),
    )


@dataclass(frozen=True, slots=True)
class KrigingInterpolator:
    """A fitted ordinary-kriging model."""

    points: np.ndarray
    values: np.ndarray
    params: KrigingParams
    crs: str
    _model: object

    @property
    def method(self) -> SpatialMethod:
        """Return the method of this interpolator."""
        return SpatialMethod.KRIGING

    def predict(self, grid_points: np.ndarray) -> Prediction:
        """Predict at grid points, returning kriging standard deviation as uncertainty."""
        from pykrige.ok import OrdinaryKriging

        grid_points = np.asarray(grid_points, dtype=float).reshape(-1, 2)
        model: OrdinaryKriging = self._model
        values, variance = model.execute(
            "points", grid_points[:, 0], grid_points[:, 1], backend="vectorized"
        )
        values = np.asarray(values, dtype=float).reshape(-1)
        variance = np.maximum(np.asarray(variance, dtype=float).reshape(-1), 0.0)
        support = pairwise_distances(grid_points, self.points, crs=self.crs).min(axis=1)
        return Prediction(values=values, uncertainty=np.sqrt(variance), support=support)


def fit_kriging(
    points: np.ndarray, values: np.ndarray, *, spec: SpatialMethodSpec, crs: str
) -> KrigingInterpolator:
    """Fit ordinary kriging to observations in a projected CRS."""
    from pykrige.ok import OrdinaryKriging

    points = np.asarray(points, dtype=float).reshape(-1, 2)
    values = np.asarray(values, dtype=float).reshape(-1)
    if len(points) != len(values) or len(points) < 3:
        raise ValidationError(
            "Kriging needs at least three observations.",
            details={"points": len(points)},
        )
    params = _params_from(spec)
    model = OrdinaryKriging(
        points[:, 0],
        points[:, 1],
        values,
        variogram_model=params.variogram_model,
        nlags=params.nlags,
        anisotropy_scaling=params.anisotropy_scaling,
        verbose=False,
        enable_plotting=False,
    )
    return KrigingInterpolator(points=points, values=values, params=params, crs=crs, _model=model)
