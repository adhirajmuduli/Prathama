"""Maps recipe method identifiers to validated functional implementations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

import numpy as np

from trendsmapp.domain.enums import SpatialMethod
from trendsmapp.errors import ValidationError
from trendsmapp.spatial.base import (
    FittedInterpolator,
    MethodCapability,
    SpatialMethodSpec,
)
from trendsmapp.spatial.gaussian_process import MAX_GP_POINTS, fit_gaussian_process
from trendsmapp.spatial.idw import fit_idw
from trendsmapp.spatial.kriging import fit_kriging
from trendsmapp.spatial.rbf import fit_rbf

__all__ = [
    "METHOD_CAPABILITIES",
    "METHOD_REGISTRY",
    "MethodEntry",
    "capability_for",
    "fit_method",
    "validate_methods",
]


@dataclass(frozen=True, slots=True)
class MethodEntry:
    """One registered spatial method."""

    method: SpatialMethod
    capability: MethodCapability
    factory: Callable[..., FittedInterpolator]


def _entry(
    method: SpatialMethod,
    factory: Callable[..., FittedInterpolator],
    *,
    max_points: int | None,
    provides_uncertainty: bool,
    description: str,
) -> MethodEntry:
    return MethodEntry(
        method=method,
        capability=MethodCapability(
            method=method,
            max_points=max_points,
            provides_uncertainty=provides_uncertainty,
            description=description,
        ),
        factory=factory,
    )


#: The registry of implemented spatial methods.
METHOD_REGISTRY: Final[dict[SpatialMethod, MethodEntry]] = {
    SpatialMethod.IDW: _entry(
        SpatialMethod.IDW,
        fit_idw,
        max_points=None,
        provides_uncertainty=False,
        description="Deterministic inverse-distance weighting with a distance floor.",
    ),
    SpatialMethod.RBF: _entry(
        SpatialMethod.RBF,
        fit_rbf,
        max_points=None,
        provides_uncertainty=False,
        description="SciPy radial-basis-function interpolation.",
    ),
    SpatialMethod.KRIGING: _entry(
        SpatialMethod.KRIGING,
        fit_kriging,
        max_points=None,
        provides_uncertainty=True,
        description="PyKrige ordinary kriging with variogram-based variance.",
    ),
    SpatialMethod.GAUSSIAN_PROCESS: _entry(
        SpatialMethod.GAUSSIAN_PROCESS,
        fit_gaussian_process,
        max_points=MAX_GP_POINTS,
        provides_uncertainty=True,
        description="scikit-learn Gaussian process with predictive standard deviation.",
    ),
}


def capability_for(method: SpatialMethod) -> MethodCapability:
    """Return the capability of a registered method."""
    entry = METHOD_REGISTRY.get(method)
    if entry is None:
        raise ValidationError(
            f"The spatial method '{method.value}' is not implemented.",
            details={
                "method": method.value,
                "implemented": sorted(m.value for m in METHOD_REGISTRY),
            },
        )
    return entry.capability


#: Capabilities of every registered method, keyed by method.
METHOD_CAPABILITIES: Final[dict[SpatialMethod, MethodCapability]] = {
    method: entry.capability for method, entry in METHOD_REGISTRY.items()
}


def validate_methods(specs: list[SpatialMethodSpec]) -> None:
    """Validate that every spec names an implemented method and unique names."""
    seen: set[SpatialMethod] = set()
    for spec in specs:
        capability_for(spec.method)  # raises for unknown methods
        if spec.method in seen:
            raise ValidationError(
                f"The method '{spec.method.value}' is configured twice.",
                details={"method": spec.method.value},
            )
        seen.add(spec.method)


def fit_method(
    spec: SpatialMethodSpec,
    points: np.ndarray,
    values: np.ndarray,
    *,
    crs: str,
) -> FittedInterpolator:
    """Fit one method from a recipe spec, enforcing its capability cap."""
    entry = METHOD_REGISTRY.get(spec.method)
    if entry is None:
        raise ValidationError(
            f"The spatial method '{spec.method.value}' is not implemented.",
            details={"implemented": sorted(m.value for m in METHOD_REGISTRY)},
        )
    cap = entry.capability
    if cap.max_points is not None and len(points) > cap.max_points:
        from trendsmapp.errors import ResourceLimitError

        raise ResourceLimitError(
            f"The frame has more observations than method '{spec.method.value}' accepts.",
            details={"points": len(points), "max_points": cap.max_points},
        )
    return entry.factory(points, values, spec=spec, crs=crs)
