"""Regression metrics, bootstrap confidence intervals, fold aggregation, subgroup metrics."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Final, Sequence

import numpy as np

__all__ = [
    "BOOTSTRAP_SAMPLES",
    "aggregate_fold_metrics",
    "bootstrap_ci",
    "regression_metrics",
    "subgroup_metrics",
]

#: Bootstrap resamples for confidence intervals.
BOOTSTRAP_SAMPLES: Final[int] = 1_000


def regression_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    """Return MAE, RMSE, bias, R², and count for one prediction set."""
    y_true = np.asarray(y_true, dtype=float).reshape(-1)
    y_pred = np.asarray(y_pred, dtype=float).reshape(-1)
    if len(y_true) != len(y_pred):
        raise ValueError("y_true and y_pred must align.")
    if len(y_true) == 0:
        return {"mae": float("nan"), "rmse": float("nan"), "bias": float("nan"), "r2": float("nan"), "n": 0.0}
    errors = y_pred - y_true
    mae = float(np.mean(np.abs(errors)))
    rmse = float(np.sqrt(np.mean(errors**2)))
    bias = float(np.mean(errors))
    mean = float(np.mean(y_true))
    ss_res = float(np.sum(errors**2))
    ss_tot = float(np.sum((y_true - mean) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return {"mae": mae, "rmse": rmse, "bias": bias, "r2": r2, "n": float(len(y_true))}


def bootstrap_ci(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    *,
    seed: int = 0,
    samples: int = BOOTSTRAP_SAMPLES,
    metric: str = "rmse",
) -> tuple[float, float]:
    """Return the percentile bootstrap CI of one metric over resampled rows."""
    y_true = np.asarray(y_true, dtype=float).reshape(-1)
    y_pred = np.asarray(y_pred, dtype=float).reshape(-1)
    n = len(y_true)
    if n == 0:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    values: list[float] = []
    for _ in range(samples):
        idx = rng.integers(0, n, size=n)
        values.append(regression_metrics(y_true[idx], y_pred[idx])[metric])
    low = float(np.percentile(values, 2.5))
    high = float(np.percentile(values, 97.5))
    return (min(low, high), max(low, high))


def aggregate_fold_metrics(fold_metrics: Sequence[dict[str, float]]) -> dict[str, Any]:
    """Aggregate per-fold metric dicts into mean/std per metric plus fold count."""
    if not fold_metrics:
        return {"folds": 0}
    keys = [key for key in fold_metrics[0] if key != "n"]
    aggregated: dict[str, Any] = {"folds": len(fold_metrics)}
    for key in keys:
        values = np.asarray(
            [fold[key] for fold in fold_metrics if np.isfinite(fold.get(key, float("nan")))],
            dtype=float,
        )
        aggregated[f"{key}_mean"] = float(np.mean(values)) if values.size else float("nan")
        aggregated[f"{key}_std"] = float(np.std(values)) if values.size else float("nan")
    aggregated["n_total"] = float(sum(fold.get("n", 0.0) for fold in fold_metrics))
    return aggregated


def subgroup_metrics(
    y_true: np.ndarray, y_pred: np.ndarray, groups: Sequence[str]
) -> dict[str, dict[str, float]]:
    """Return per-group regression metrics."""
    y_true = np.asarray(y_true, dtype=float).reshape(-1)
    y_pred = np.asarray(y_pred, dtype=float).reshape(-1)
    buckets: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for index, group in enumerate(groups):
        buckets[group].append((int(y_true[index]), int(y_pred[index])))
    result: dict[str, dict[str, float]] = {}
    for group in sorted(buckets):
        pairs = buckets[group]
        result[group] = regression_metrics(
            np.asarray([p[0] for p in pairs], dtype=float),
            np.asarray([p[1] for p in pairs], dtype=float),
        )
    return result
