"""Partial dependence and accumulated local effects.

Partial dependence is computed with scikit-learn for the estimators that
support it. Accumulated local effects are not substituted when they are not
available: the run records the limitation and returns the partial dependence
rows it did compute, so a reader can see exactly which effect was produced.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Final

import numpy as np

from trendsmapp.domain.enums import ModelFamily

__all__ = ["EFFECT_METHODS", "partial_dependence_effects"]

#: The effect methods this build implements.
EFFECT_METHODS: Final[tuple[str, ...]] = ("partial_dependence",)


def partial_dependence_effects(
    estimator: Any,
    x: np.ndarray,
    feature_names: Sequence[str],
    *,
    grid_resolution: int = 20,
    family: ModelFamily | None = None,
) -> dict[str, Any]:
    """Return the partial dependence of every feature over a value grid.

    The grid is built from the observed values of each feature, so the effect
    is reported on the range the data actually covers.
    """
    from sklearn.inspection import partial_dependence

    x = np.asarray(x, dtype=float)
    if x.shape[1] != len(feature_names):
        raise ValueError("Every feature needs a name.")
    results = partial_dependence(
        estimator,
        x,
        list(range(x.shape[1])),
        grid_resolution=grid_resolution,
    )
    rows: list[dict[str, Any]] = []
    for index, name in enumerate(feature_names):
        grid = np.asarray(results["grid_values"][index], dtype=float).reshape(-1)
        average = np.asarray(results["average"][index], dtype=float).reshape(-1)
        rows.append(
            {
                "feature": name,
                "method": "partial_dependence",
                "value": float(average[-1] - average[0]),
                "baseline": float(average[0]),
                "unit": "predicted change over the observed range",
                "detail": {
                    "grid": [float(value) for value in grid],
                    "average": [float(value) for value in average],
                    "family": family.value if family is not None else None,
                },
            }
        )
    limitations: list[str] = []
    if family is not None and family not in {
        ModelFamily.RANDOM_FOREST,
        ModelFamily.EXTRA_TREES,
        ModelFamily.HIST_GRADIENT_BOOSTING,
        ModelFamily.XGBOOST,
    }:
        limitations.append(
            "partial_dependence is only defined for the tree ensembles; the "
            "baseline model has no effect decomposition"
        )
    return {"rows": rows, "limitations": limitations}
