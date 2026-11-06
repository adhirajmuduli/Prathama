"""Validation splits: leave-one-station-out, grouped holdout, spatial blocks.

Every split is deterministic: folds are ordered by sorted group key, so the
same data always produces the same folds and the same metrics. Metrics are
computed before any method comparison, and the selection rule can only use
these recorded metrics.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import numpy as np

from trendsmapp.spatial.base import (
    FoldMetrics,
    SpatialMethodSpec,
    compute_metrics,
)

__all__ = [
    "grouped_holdout",
    "leave_one_station_out",
    "spatial_block_holdout",
    "validate_method",
]

#: Default spatial block size in metres.
DEFAULT_BLOCK_SIZE_M: float = 5_000.0


def leave_one_station_out(
    points: np.ndarray,
    values: np.ndarray,
    station_ids: Sequence[str],
    *,
    spec: SpatialMethodSpec,
    crs: str,
    fit_predict: Callable[[np.ndarray, np.ndarray, np.ndarray], np.ndarray],
) -> FoldMetrics:
    """Leave one station out per fold and score the held-out observations.

    ``fit_predict(train_points, train_values, test_points)`` must return the
    predictions at ``test_points``.
    """
    points = np.asarray(points, dtype=float).reshape(-1, 2)
    values = np.asarray(values, dtype=float).reshape(-1)
    station_ids = list(station_ids)
    if len(station_ids) != len(points):
        raise ValueError("station_ids must align with points")
    errors: list[float] = []
    folds = 0
    for station in sorted(set(station_ids)):
        held = [i for i, s in enumerate(station_ids) if s == station]
        train = [i for i in range(len(points)) if station_ids[i] != station]
        if not held or not train:
            continue
        folds += 1
        predictions = fit_predict(points[train], values[train], points[held])
        errors.extend((values[held] - predictions).tolist())
    metrics = compute_metrics(np.asarray(errors, dtype=float))
    return FoldMetrics(
        mae=metrics.mae,
        rmse=metrics.rmse,
        bias=metrics.bias,
        valid_count=metrics.valid_count,
        fold_count=folds,
    )


def grouped_holdout(
    points: np.ndarray,
    values: np.ndarray,
    groups: Sequence[str],
    *,
    spec: SpatialMethodSpec,
    crs: str,
    fit_predict: Callable[[np.ndarray, np.ndarray, np.ndarray], np.ndarray],
    max_folds: int | None = None,
) -> FoldMetrics:
    """Hold out one group per fold; ``groups`` may be stations, sectors, or years."""
    points = np.asarray(points, dtype=float).reshape(-1, 2)
    values = np.asarray(values, dtype=float).reshape(-1)
    groups = list(groups)
    if len(groups) != len(points):
        raise ValueError("groups must align with points")
    errors: list[float] = []
    folds = 0
    unique_groups = sorted(set(groups))
    if max_folds is not None:
        unique_groups = unique_groups[:max_folds]
    for group in unique_groups:
        held = [i for i, g in enumerate(groups) if g == group]
        train = [i for i in range(len(points)) if groups[i] != group]
        if not held or not train:
            continue
        folds += 1
        predictions = fit_predict(points[train], values[train], points[held])
        errors.extend((values[held] - predictions).tolist())
    metrics = compute_metrics(np.asarray(errors, dtype=float))
    return FoldMetrics(
        mae=metrics.mae,
        rmse=metrics.rmse,
        bias=metrics.bias,
        valid_count=metrics.valid_count,
        fold_count=folds,
    )


def spatial_block_ids(
    points: np.ndarray, *, block_size_m: float = DEFAULT_BLOCK_SIZE_M
) -> list[int]:
    """Assign each point a spatial block id from its projected coordinates."""
    points = np.asarray(points, dtype=float).reshape(-1, 2)
    if block_size_m <= 0:
        raise ValueError("block_size_m must be positive")
    blocks = (points // block_size_m).astype(np.int64)
    # Map (bx, by) pairs to dense ids deterministically.
    _unique, inverse = np.unique(blocks, axis=0, return_inverse=True)
    return [int(item) for item in inverse.tolist()]


def spatial_block_holdout(
    points: np.ndarray,
    values: np.ndarray,
    *,
    spec: SpatialMethodSpec,
    crs: str,
    fit_predict: Callable[[np.ndarray, np.ndarray, np.ndarray], np.ndarray],
    block_size_m: float = DEFAULT_BLOCK_SIZE_M,
) -> FoldMetrics:
    """Leave one spatial block out per fold."""
    block_ids = spatial_block_ids(points, block_size_m=block_size_m)
    return grouped_holdout(
        points, values, [str(b) for b in block_ids], spec=spec, crs=crs, fit_predict=fit_predict
    )


def validate_method(
    spec: SpatialMethodSpec,
    points: np.ndarray,
    values: np.ndarray,
    station_ids: Sequence[str],
    *,
    crs: str,
    fit_predict: Callable[[np.ndarray, np.ndarray, np.ndarray], np.ndarray],
) -> FoldMetrics:
    """Run leave-one-station-out validation for one method on one frame."""
    return leave_one_station_out(
        points, values, station_ids, spec=spec, crs=crs, fit_predict=fit_predict
    )
