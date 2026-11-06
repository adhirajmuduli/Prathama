"""Normalize method-specific uncertainty and support into one payload.

Methods that return a variance (kriging) or a standard deviation (GP) get
their native uncertainty. IDW and RBF have none, so their payload is explicit
about being support-based: the uncertainty field is null and the support
distance is the only uncertainty diagnostic. A consumer can therefore always
tell which kind of uncertainty it is reading.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from trendsmapp.domain.enums import SpatialMethod

__all__ = ["UncertaintyPayload", "normalize_uncertainty"]


@dataclass(frozen=True, slots=True)
class UncertaintyPayload:
    """The common uncertainty payload of one method on one frame."""

    method: SpatialMethod
    kind: str  # "kriging_std" | "gp_std" | "support_only"
    #: Per-grid-point uncertainty values, when the method provides them.
    values: np.ndarray | None
    #: Per-grid-point distance in metres to the nearest observation.
    support_m: np.ndarray


def normalize_uncertainty(
    method: SpatialMethod,
    *,
    raw_uncertainty: np.ndarray | None,
    support_m: np.ndarray,
) -> UncertaintyPayload:
    """Normalize one method's uncertainty into the common payload."""
    support_m = np.asarray(support_m, dtype=float)
    if method is SpatialMethod.KRIGING:
        kind = "kriging_std"
    elif method is SpatialMethod.GAUSSIAN_PROCESS:
        kind = "gp_std"
    else:
        kind = "support_only"
    if raw_uncertainty is not None and kind != "support_only":
        values = np.maximum(np.asarray(raw_uncertainty, dtype=float), 0.0)
    else:
        values = None
    return UncertaintyPayload(method=method, kind=kind, values=values, support_m=support_m)
