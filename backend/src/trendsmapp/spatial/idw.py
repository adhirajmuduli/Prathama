"""Deterministic inverse-distance-weighting interpolation.

IDW is the transparent baseline. The distance floor prevents a single
co-located observation from dominating the entire grid, the power controls the
falloff, and the optional neighbor limit keeps the computation local and
deterministic. Exact matches (distance zero) take the observed value directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np

from trendsmapp.domain.enums import SpatialMethod
from trendsmapp.errors import ResourceLimitError, ValidationError
from trendsmapp.geospatial.distance import nearest_neighbor_distances, pairwise_distances
from trendsmapp.spatial.base import (
    DEFAULT_DISTANCE_FLOOR_M,
    Prediction,
    SpatialMethodSpec,
)

__all__ = ["IDWParams", "IdwInterpolator", "fit_idw"]

#: Distances at or below this many meters count as a coincident observation.
_COINCIDENT_EPS_M: Final[float] = 1e-9

#: Default IDW power.
DEFAULT_IDW_POWER: Final[float] = 2.0

#: Default cap on neighbors used per grid cell.
DEFAULT_IDW_MAX_NEIGHBORS: Final[int] = 32


@dataclass(frozen=True, slots=True)
class IDWParams:
    """Validated IDW parameters."""

    power: float = DEFAULT_IDW_POWER
    distance_floor_m: float = DEFAULT_DISTANCE_FLOOR_M
    max_neighbors: int | None = DEFAULT_IDW_MAX_NEIGHBORS

    def __post_init__(self) -> None:
        if self.power <= 0:
            raise ValidationError(
                "The IDW power must be positive.",
                details={"power": self.power},
            )
        if self.distance_floor_m <= 0:
            raise ValidationError(
                "The distance floor must be positive.",
                details={"distance_floor_m": self.distance_floor_m},
            )
        if self.max_neighbors is not None and self.max_neighbors < 1:
            raise ValidationError(
                "The neighbor limit must be at least one.",
                details={"max_neighbors": self.max_neighbors},
            )


def _params_from(spec: SpatialMethodSpec) -> IDWParams:
    """Build validated IDW parameters from a recipe spec."""
    if spec.method is not SpatialMethod.IDW:
        raise ValidationError(
            f"IDW parameters cannot configure method '{spec.method.value}'.",
            details={"method": spec.method.value},
        )
    unknown = set(spec.params) - {"power", "distance_floor_m", "max_neighbors"}
    if unknown:
        raise ValidationError(
            "Unknown IDW parameters.",
            details={
                "unknown": sorted(unknown),
                "allowed": ["power", "distance_floor_m", "max_neighbors"],
            },
        )
    return IDWParams(
        power=float(spec.params.get("power", DEFAULT_IDW_POWER)),
        distance_floor_m=float(spec.params.get("distance_floor_m", DEFAULT_DISTANCE_FLOOR_M)),
        max_neighbors=(
            int(spec.params["max_neighbors"])
            if spec.params.get("max_neighbors") is not None
            else None
        ),
    )


@dataclass(frozen=True, slots=True)
class IdwInterpolator:
    """A fitted IDW model."""

    points: np.ndarray
    values: np.ndarray
    params: IDWParams
    crs: str

    @property
    def method(self) -> SpatialMethod:
        """Return the method of this interpolator."""
        return SpatialMethod.IDW

    def predict(self, grid_points: np.ndarray) -> Prediction:
        """Predict at grid points in the same CRS as the fit points."""
        grid_points = np.asarray(grid_points, dtype=float).reshape(-1, 2)
        if len(self.points) == 0:
            raise ValidationError(
                "IDW cannot predict without observations.",
                details={"reason": "no_observations"},
            )
        distances = pairwise_distances(grid_points, self.points, crs=self.crs)
        nearest_neighbor_distances(self.points, crs=self.crs)
        nearest = distances.min(axis=1)

        power = self.params.power
        floor = self.params.distance_floor_m
        effective = np.maximum(distances, floor)
        weights = 1.0 / (effective**power)

        if self.params.max_neighbors is not None:
            k = min(self.params.max_neighbors, len(self.points))
            order = np.argsort(distances, axis=1, kind="stable")
            np.arange(len(grid_points))
            selected = order[:, :k]
            selected_distances = np.take_along_axis(distances, selected, axis=1)
            selected_weights = 1.0 / (np.maximum(selected_distances, floor) ** power)
            numerator = (selected_weights * self.values[selected]).sum(axis=1)
            denominator = selected_weights.sum(axis=1)
            values = numerator / np.where(
                np.isclose(denominator, 0.0, atol=1e-12), 1.0, denominator
            )
        else:
            numerator = (weights * self.values[None, :]).sum(axis=1)
            denominator = weights.sum(axis=1)
            values = numerator / np.where(
                np.isclose(denominator, 0.0, atol=1e-12), 1.0, denominator
            )
        # Coincident observations (distance zero) take their average; a unique
        # exact match takes its value directly. Distances are non-negative, so
        # a <= epsilon test replaces a float == 0.0 comparison.
        exact = nearest <= _COINCIDENT_EPS_M
        if np.any(exact):
            coincident = distances[exact] <= _COINCIDENT_EPS_M
            values[exact] = (self.values[None, :] * coincident).sum(axis=1) / coincident.sum(axis=1)
        return Prediction(values=values, uncertainty=None, support=nearest)


def fit_idw(
    points: np.ndarray, values: np.ndarray, *, spec: SpatialMethodSpec, crs: str
) -> IdwInterpolator:
    """Fit IDW to observations in a projected CRS."""
    points = np.asarray(points, dtype=float).reshape(-1, 2)
    values = np.asarray(values, dtype=float).reshape(-1)
    if len(points) != len(values):
        raise ValidationError(
            "Points and values must have the same length.",
            details={"points": len(points), "values": len(values)},
        )
    if len(points) < 1:
        raise ValidationError(
            "IDW needs at least one observation.", details={"reason": "no_observations"}
        )
    if not np.all(np.isfinite(values)):
        raise ResourceLimitError(
            "IDW cannot fit non-finite values; they are flagged by QC.",
            details={"reason": "non_finite_values"},
        )
    return IdwInterpolator(points=points, values=values, params=_params_from(spec), crs=crs)
