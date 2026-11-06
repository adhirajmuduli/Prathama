"""Descriptive trend estimates: Theil-Sen slope, confidence interval, autocorrelation note.

The slope is the median of pairwise slopes (Theil-Sen), which tolerates the
outliers QC flags but does not delete. The confidence interval is a bootstrap
over residuals with the configured seed, and the lag-1 autocorrelation of the
residuals is reported so a reader can see whether the interval is optimistic.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np

from trendsmapp.errors import ValidationError

__all__ = ["TrendEstimate", "theil_sen_trend"]

#: Bootstrap resamples for the confidence interval.
DEFAULT_BOOTSTRAP_SAMPLES: Final[int] = 1_000


@dataclass(frozen=True, slots=True)
class TrendEstimate:
    """One trend estimate with its diagnostics."""

    slope_per_day: float
    intercept: float
    ci95_per_day: tuple[float, float]
    residual_autocorr_lag1: float
    n_points: int
    bootstrap_samples: int


def theil_sen_trend(
    times_seconds: Sequence[float],
    values: Sequence[float],
    *,
    seed: int = 0,
    bootstrap_samples: int = DEFAULT_BOOTSTRAP_SAMPLES,
) -> TrendEstimate:
    """Estimate the trend of a series in units per day."""
    t = np.asarray(times_seconds, dtype=float)
    v = np.asarray(values, dtype=float)
    if len(t) != len(v) or len(t) < 3:
        raise ValidationError(
            "A trend needs at least three points.",
            details={"points": len(t)},
        )
    if np.any(~np.isfinite(v)):
        raise ValidationError(
            "Non-finite values cannot be trended.",
            details={"reason": "non_finite_values"},
        )
    t_days = (t - t[0]) / 86_400.0
    # Theil-Sen slope: median of pairwise slopes.
    slopes: list[float] = []
    for i in range(len(t_days)):
        for j in range(i + 1, len(t_days)):
            dt = t_days[j] - t_days[i]
            if dt > 0:
                slopes.append((v[j] - v[i]) / dt)
    slope = float(np.median(slopes))
    intercept = float(np.median(v - slope * t_days))
    residuals = v - (intercept + slope * t_days)
    # lag-1 autocorrelation of residuals
    if len(residuals) > 2 and np.std(residuals) > 0:
        r = residuals[:-1]
        s = residuals[1:]
        autocorr = float(np.corrcoef(r, s)[0, 1])
    else:
        autocorr = 0.0
    # bootstrap CI over residual resampling, deterministic under the seed
    rng = np.random.default_rng(seed)
    boot_slopes: list[float] = []
    fitted = intercept + slope * t_days
    for _ in range(bootstrap_samples):
        resampled = fitted + rng.choice(residuals, size=len(residuals), replace=True)
        boot_slopes.append(_ols_slope(t_days, resampled))
    ci_low = float(np.percentile(boot_slopes, 2.5))
    ci_high = float(np.percentile(boot_slopes, 97.5))
    return TrendEstimate(
        slope_per_day=slope,
        intercept=intercept,
        ci95_per_day=(min(ci_low, ci_high), max(ci_low, ci_high)),
        residual_autocorr_lag1=autocorr,
        n_points=len(t),
        bootstrap_samples=bootstrap_samples,
    )


def _ols_slope(t_days: np.ndarray, values: np.ndarray) -> float:
    """Ordinary least-squares slope in units per day."""
    if len(t_days) < 2 or np.all(t_days == t_days[0]):
        return 0.0
    return float(np.polyfit(t_days, values, 1)[0])
