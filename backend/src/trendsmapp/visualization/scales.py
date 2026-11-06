"""Scale calculation for concentration-like surfaces.

Four policies: physical (data min/max), robust (percentile clipping),
global-sequence (one scale across every frame of an animation), and a
user-declared range. A policy is always recorded with the output so a reader
knows which one was used.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

import numpy as np

from trendsmapp.errors import ValidationError

__all__ = ["ROBUST_PERCENTILE", "ScalePolicy", "ScaleResult", "compute_scale"]

#: Percentile used by the robust policy.
ROBUST_PERCENTILE: Final[float] = 5.0


class ScalePolicy(StrEnum):
    """The scale policies a visualization may declare."""

    PHYSICAL = "physical"
    ROBUST = "robust"
    GLOBAL_SEQUENCE = "global_sequence"
    USER = "user"


@dataclass(frozen=True, slots=True)
class ScaleResult:
    """The computed scale and the policy that produced it."""

    vmin: float
    vmax: float
    policy: ScalePolicy


def compute_scale(
    values_per_frame: Sequence[np.ndarray],
    *,
    policy: ScalePolicy = ScalePolicy.PHYSICAL,
    user_range: tuple[float, float] | None = None,
    robust_percentile: float = ROBUST_PERCENTILE,
) -> ScaleResult:
    """Compute one scale across the given frames under the declared policy."""
    if policy is ScalePolicy.USER:
        if user_range is None:
            raise ValidationError(
                "The user scale policy requires a declared range.",
                details={"reason": "missing_user_range"},
            )
        low, high = float(user_range[0]), float(user_range[1])
        if not low < high:
            raise ValidationError(
                "The declared scale range is inverted.",
                details={"range": [low, high]},
            )
        return ScaleResult(vmin=low, vmax=high, policy=policy)

    finite = np.concatenate([np.asarray(frame, dtype=float).ravel() for frame in values_per_frame])
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        return ScaleResult(vmin=0.0, vmax=1.0, policy=policy)

    if policy is ScalePolicy.ROBUST:
        low = float(np.percentile(finite, robust_percentile))
        high = float(np.percentile(finite, 100.0 - robust_percentile))
    else:
        low = float(finite.min())
        high = float(finite.max())
    if high <= low:
        high = low + 1.0
    return ScaleResult(vmin=low, vmax=high, policy=policy)
