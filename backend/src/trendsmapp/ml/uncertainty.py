"""Uncertainty intervals: bootstrap ensemble or quantile, with empirical coverage."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

import numpy as np

from trendsmapp.domain.enums import UncertaintyMethod
from trendsmapp.errors import ValidationError

__all__ = [
    "BOOTSTRAP_REPLICATES",
    "QUANTILES",
    "FitPredict",
    "UncertaintyResult",
    "compute_uncertainty",
]

#: ``fit_predict(x_train, y_train, seed)`` fits on a bootstrap subset and returns
#: a function mapping feature rows to predictions.
FitPredict = Callable[[np.ndarray, np.ndarray, int], Callable[[np.ndarray], np.ndarray]]

#: Bootstrap replicates for the ensemble interval.
BOOTSTRAP_REPLICATES: Final[int] = 20

#: Quantile levels for the quantile interval.
QUANTILES: Final[tuple[float, float]] = (0.05, 0.95)


@dataclass(frozen=True, slots=True)
class UncertaintyResult:
    """One uncertainty computation."""

    method: UncertaintyMethod
    lower: np.ndarray
    upper: np.ndarray
    empirical_coverage: float | None
    notes: tuple[str, ...]


def compute_uncertainty(
    method: UncertaintyMethod,
    *,
    fit_predict: FitPredict,
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_test: np.ndarray,
    y_test: np.ndarray | None,
    seed: int,
) -> UncertaintyResult:
    """Compute prediction intervals on the test rows.

    ``fit_predict(x_train_subset, y_train_subset, seed) -> predict_fn`` must
    fit a model and return a function mapping feature rows to predictions.
    Coverage is measured against ``y_test`` when supplied.
    """
    if method is UncertaintyMethod.BOOTSTRAP_ENSEMBLE:
        return _bootstrap_ensemble(fit_predict, x_train, y_train, x_test, y_test, seed)
    if method is UncertaintyMethod.QUANTILE:
        return _quantile_interval(fit_predict, x_train, y_train, x_test, y_test, seed)
    raise ValidationError(f"Unknown uncertainty method '{getattr(method, 'value', method)}'.")


def _bootstrap_ensemble(
    fit_predict: FitPredict,
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_test: np.ndarray,
    y_test: np.ndarray | None,
    seed: int,
) -> UncertaintyResult:
    """Percentile interval from a bootstrap ensemble."""
    rng = np.random.default_rng(seed)
    n = len(y_train)
    predictions: list[np.ndarray] = []
    for replicate in range(BOOTSTRAP_REPLICATES):
        idx = rng.integers(0, n, size=n)
        predict = fit_predict(x_train[idx], y_train[idx], seed + replicate)
        predictions.append(np.asarray(predict(x_test), dtype=float))
    stacked = np.stack(predictions)
    lower = np.percentile(stacked, 5, axis=0)
    upper = np.percentile(stacked, 95, axis=0)
    coverage = _coverage(lower, upper, y_test)
    return UncertaintyResult(
        method=UncertaintyMethod.BOOTSTRAP_ENSEMBLE,
        lower=lower,
        upper=upper,
        empirical_coverage=coverage,
        notes=(f"{BOOTSTRAP_REPLICATES} bootstrap replicates",),
    )


def _quantile_interval(
    fit_predict: FitPredict,
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_test: np.ndarray,
    y_test: np.ndarray | None,
    seed: int,
) -> UncertaintyResult:
    """Interval from two quantile regressors."""
    from sklearn.ensemble import HistGradientBoostingRegressor

    lower_model = HistGradientBoostingRegressor(
        loss="quantile", quantile=QUANTILES[0], max_iter=200, random_state=seed
    )
    upper_model = HistGradientBoostingRegressor(
        loss="quantile", quantile=QUANTILES[1], max_iter=200, random_state=seed
    )
    lower_model.fit(x_train, y_train)
    upper_model.fit(x_train, y_train)
    lower = np.asarray(lower_model.predict(x_test), dtype=float)
    upper = np.asarray(upper_model.predict(x_test), dtype=float)
    coverage = _coverage(lower, upper, y_test)
    return UncertaintyResult(
        method=UncertaintyMethod.QUANTILE,
        lower=lower,
        upper=upper,
        empirical_coverage=coverage,
        notes=(f"quantiles {QUANTILES}",),
    )


def _coverage(lower: np.ndarray, upper: np.ndarray, y_test: np.ndarray | None) -> float | None:
    """Return the fraction of test values inside the interval, when known."""
    if y_test is None:
        return None
    y_test = np.asarray(y_test, dtype=float).reshape(-1)
    inside = (y_test >= lower) & (y_test <= upper)
    return float(np.mean(inside)) if len(y_test) else None
