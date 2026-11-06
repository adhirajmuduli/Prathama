"""Common interpolator protocol, result models, and method capabilities.

Every spatial method is a pure function from observations to grid predictions.
A fitted interpolator never mutates its inputs, and every prediction carries
the distance to the nearest observation as its support diagnostic, so a reader
can always see how far a cell is from measured data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final, Protocol

import numpy as np

from trendsmapp.domain.enums import SpatialMethod
from trendsmapp.errors import ValidationError

__all__ = [
    "FittedInterpolator",
    "FoldMetrics",
    "Interpolator",
    "MethodCapability",
    "Prediction",
    "SpatialMethodSpec",
    "compute_metrics",
]

#: Distance floor default in metres: cells closer than this to an observation
#: use that observation's value directly (IDW) or get full weight.
DEFAULT_DISTANCE_FLOOR_M: Final[float] = 1.0


@dataclass(frozen=True, slots=True)
class SpatialMethodSpec:
    """The recipe's configuration of one spatial method."""

    method: SpatialMethod
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.method, SpatialMethod):
            raise ValidationError(
                f"'{self.method}' is not a spatial method.",
                details={"allowed": [m.value for m in SpatialMethod]},
            )


@dataclass(frozen=True, slots=True)
class Prediction:
    """The prediction of one fitted method at grid points."""

    values: np.ndarray
    #: Method-specific uncertainty per grid point, when the method provides it.
    uncertainty: np.ndarray | None
    #: Distance in metres from each grid point to the nearest observation.
    support: np.ndarray

    def __post_init__(self) -> None:
        if self.values.ndim != 1:
            raise ValueError("Prediction values must be a 1-D array over grid points.")
        if self.uncertainty is not None and self.uncertainty.shape != self.values.shape:
            raise ValueError("Uncertainty must have the same shape as values.")
        if self.support.shape != self.values.shape:
            raise ValueError("Support must have the same shape as values.")


class FittedInterpolator(Protocol):
    """A fitted method that can predict at arbitrary points."""

    @property
    def method(self) -> SpatialMethod: ...

    def predict(self, points: np.ndarray) -> Prediction: ...


class Interpolator(Protocol):
    """A factory that fits a method to observations."""

    def fit(
        self, points: np.ndarray, values: np.ndarray, *, spec: SpatialMethodSpec
    ) -> FittedInterpolator: ...


@dataclass(frozen=True, slots=True)
class MethodCapability:
    """What a method can and cannot do."""

    method: SpatialMethod
    #: Maximum observations the method accepts; None means no cap.
    max_points: int | None
    #: Whether the method returns a native variance/uncertainty estimate.
    provides_uncertainty: bool
    description: str


@dataclass(frozen=True, slots=True)
class FoldMetrics:
    """Validation metrics of one method on one frame."""

    mae: float
    rmse: float
    bias: float
    valid_count: int
    fold_count: int


def compute_metrics(errors: np.ndarray) -> FoldMetrics:
    """Return MAE, RMSE, bias, and counts from an array of signed errors."""
    errors = np.asarray(errors, dtype=float)
    valid = errors[np.isfinite(errors)]
    if valid.size == 0:
        return FoldMetrics(
            mae=float("nan"), rmse=float("nan"), bias=float("nan"), valid_count=0, fold_count=0
        )
    mae = float(np.mean(np.abs(valid)))
    rmse = float(np.sqrt(np.mean(valid**2)))
    bias = float(np.mean(valid))
    return FoldMetrics(
        mae=mae, rmse=rmse, bias=bias, valid_count=int(valid.size), fold_count=int(valid.size)
    )
