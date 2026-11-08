"""Held-out permutation importance with repeated seeds.

The importance of a feature is how much the model's error grows when that
feature is scrambled in the held-out rows. The rows are never permuted in the
training data, so the measure cannot reward a feature that was memorized.
Every repeat uses its own seed, and the reported value is the mean over the
repeats together with the spread, so a reader can see whether the ranking is
stable.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Final

import numpy as np

from trendsmapp.ml.metrics import regression_metrics

__all__ = ["DEFAULT_REPEATS", "permutation_importance"]

#: Default number of permutation repeats.
DEFAULT_REPEATS: Final[int] = 10


def permutation_importance(
    predict: Callable[[np.ndarray], np.ndarray],
    x: np.ndarray,
    y: np.ndarray,
    feature_names: Sequence[str],
    *,
    repeats: int = DEFAULT_REPEATS,
    seed: int = 0,
    primary_metric: str = "rmse",
) -> list[dict[str, Any]]:
    """Return the held-out permutation importance of every feature.

    ``predict`` maps a feature matrix to predictions. The importance is the
    increase in the primary metric when the feature is permuted; a positive
    value means the feature carries information the model uses.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float).reshape(-1)
    if x.shape[0] != len(y):
        raise ValueError("The feature matrix and the target must align.")
    if x.shape[1] != len(feature_names):
        raise ValueError("Every feature needs a name.")
    if repeats < 1:
        raise ValueError("At least one repeat is required.")

    baseline_predictions = np.asarray(predict(x), dtype=float).reshape(-1)
    baseline = regression_metrics(y, baseline_predictions)[primary_metric]

    rows: list[dict[str, Any]] = []
    for index, name in enumerate(feature_names):
        gains: list[float] = []
        for repeat in range(repeats):
            rng = np.random.default_rng(seed + repeat * 1009 + index)
            permuted = x.copy()
            permuted[:, index] = rng.permutation(permuted[:, index])
            predictions = np.asarray(predict(permuted), dtype=float).reshape(-1)
            score = regression_metrics(y, predictions)[primary_metric]
            gains.append(score - baseline)
        values = np.asarray(gains, dtype=float)
        rows.append(
            {
                "feature": name,
                "method": "permutation",
                "value": float(np.mean(values)),
                "baseline": float(baseline),
                "unit": primary_metric,
                "detail": {
                    "repeats": repeats,
                    "std": float(np.std(values)),
                    "min": float(np.min(values)),
                    "max": float(np.max(values)),
                },
            }
        )
    ranked = sorted(rows, key=lambda row: float(row["value"]), reverse=True)
    for rank, row in enumerate(ranked, start=1):
        row["rank"] = rank
    return ranked
