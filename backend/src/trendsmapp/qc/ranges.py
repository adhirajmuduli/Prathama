"""Plausibility-range checks loaded from the versioned QC resource.

The range resource is validated at load time against the parameter registry:
a range for a parameter that does not exist is a load error, so a dataset can
never be checked against ranges for parameters it does not contain.

Range violations are flags, never deletions. The check compares the canonical
value in canonical units against the physical bounds; observations without a
canonical value (missing, censored, unconverted) are not range-checked here.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Final

from trendsmapp.domain.enums import QcFlagCode
from trendsmapp.domain.models import Observation
from trendsmapp.errors import ValidationError
from trendsmapp.normalization.parameters import ParameterRegistry, get_parameter_registry
from trendsmapp.resources import load_yaml_resource

__all__ = [
    "QC_RANGES_RESOURCE",
    "QcRanges",
    "check_ranges",
    "get_qc_ranges",
]

#: The resource document that holds plausibility ranges and detection limits.
QC_RANGES_RESOURCE: Final[str] = "qc_ranges.v1.yaml"


@dataclass(frozen=True, slots=True)
class QcRanges:
    """Validated plausibility ranges and detection limits per parameter."""

    plausibility_ranges: dict[str, tuple[float, float]]
    detection_limits: dict[str, float]

    def plausibility_range(self, parameter_id: str) -> tuple[float, float] | None:
        """Return the physical bounds of a parameter, when declared."""
        return self.plausibility_ranges.get(parameter_id)

    def detection_limit(self, parameter_id: str) -> float | None:
        """Return the declared detection limit of a parameter, when any."""
        return self.detection_limits.get(parameter_id)


def get_qc_ranges(
    registry: ParameterRegistry | None = None,
) -> QcRanges:
    """Load and validate the QC ranges resource against the parameter registry."""
    if registry is None:
        return _load_cached()
    return _load(registry)


@lru_cache(maxsize=1)
def _load_cached() -> QcRanges:
    """Load the ranges once for the process-wide parameter registry."""
    return _load(get_parameter_registry())


def _load(registry: ParameterRegistry) -> QcRanges:
    """Load the ranges, cross-checking every key against the parameter registry."""
    document = load_yaml_resource(QC_RANGES_RESOURCE)
    raw_ranges = document.get("plausibility_ranges")
    raw_limits = document.get("detection_limits", {})
    if not isinstance(raw_ranges, dict) or not raw_ranges:
        raise ValidationError(
            f"The resource '{QC_RANGES_RESOURCE}' must declare a non-empty "
            "'plausibility_ranges' mapping.",
            details={"name": QC_RANGES_RESOURCE},
        )
    if not isinstance(raw_limits, dict):
        raise ValidationError(
            f"The resource '{QC_RANGES_RESOURCE}' must declare a 'detection_limits' mapping.",
            details={"name": QC_RANGES_RESOURCE},
        )

    ranges: dict[str, tuple[float, float]] = {}
    for parameter_id, bounds in raw_ranges.items():
        if registry.get(parameter_id) is None:
            raise ValidationError(
                f"The range resource declares bounds for '{parameter_id}', which is "
                "not in the parameter registry.",
                details={"parameter": parameter_id, "name": QC_RANGES_RESOURCE},
            )
        if (
            not isinstance(bounds, list)
            or len(bounds) != 2
            or not all(isinstance(b, (int, float)) and not isinstance(b, bool) for b in bounds)
        ):
            raise ValidationError(
                f"The plausibility range of '{parameter_id}' must be a pair of numbers.",
                details={"parameter": parameter_id, "bounds": bounds},
            )
        low, high = float(bounds[0]), float(bounds[1])
        if not low <= high:
            raise ValidationError(
                f"The plausibility range of '{parameter_id}' is inverted.",
                details={"parameter": parameter_id, "bounds": bounds},
            )
        ranges[parameter_id] = (low, high)

    limits: dict[str, float] = {}
    for parameter_id, limit in raw_limits.items():
        if registry.get(parameter_id) is None:
            raise ValidationError(
                f"The detection limit resource declares a limit for '{parameter_id}', "
                "which is not in the parameter registry.",
                details={"parameter": parameter_id, "name": QC_RANGES_RESOURCE},
            )
        if not isinstance(limit, (int, float)) or isinstance(limit, bool) or limit <= 0:
            raise ValidationError(
                f"The detection limit of '{parameter_id}' must be a positive number.",
                details={"parameter": parameter_id, "limit": limit},
            )
        limits[parameter_id] = float(limit)
    return QcRanges(plausibility_ranges=ranges, detection_limits=limits)


def check_ranges(
    observations: Sequence[Observation],
    ranges: QcRanges,
) -> list[tuple[int, QcFlagCode]]:
    """Flag observations whose canonical value leaves the physical range.

    Returns ``(observation_index, flag)`` pairs. Only the canonical value is
    compared, and only when it exists.
    """
    findings: list[tuple[int, QcFlagCode]] = []
    for index, observation in enumerate(observations):
        if observation.canonical_value is None or not observation.parameter_id:
            continue
        bounds = ranges.plausibility_range(observation.parameter_id)
        if bounds is None:
            continue
        low, high = bounds
        if observation.canonical_value < low:
            findings.append((index, QcFlagCode.VALUE_BELOW_PHYSICAL_RANGE))
        elif observation.canonical_value > high:
            findings.append((index, QcFlagCode.VALUE_ABOVE_PHYSICAL_RANGE))
    return findings
