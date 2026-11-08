"""SHAP values for fitted tree models, with bounded samples and an additivity check.

SHAP is only computed for families whose explainer exists. When a family has no
tree explainer, the run records a limitation instead of substituting another
method, because a substituted number with a different meaning is worse than no
number. The background set and the explained rows are bounded, and the additivity
property is checked so a silent mismatch is reported.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Final

import numpy as np

from trendsmapp.domain.enums import ModelFamily

__all__ = [
    "MAX_SHAP_BACKGROUND",
    "MAX_SHAP_ROWS",
    "SHAP_FAMILIES",
    "shap_importance",
]

#: Hard ceilings on the explained rows and the background set.
MAX_SHAP_ROWS: Final[int] = 2_000
MAX_SHAP_BACKGROUND: Final[int] = 200

#: The families whose fitted estimators have a tree explainer.
SHAP_FAMILIES: Final[frozenset[ModelFamily]] = frozenset(
    {
        ModelFamily.RANDOM_FOREST,
        ModelFamily.EXTRA_TREES,
        ModelFamily.HIST_GRADIENT_BOOSTING,
        ModelFamily.XGBOOST,
    }
)


def supports_shap(family: ModelFamily) -> bool:
    """Return whether a family has a tree explainer."""
    return family in SHAP_FAMILIES


def shap_importance(
    estimator: Any,
    x: np.ndarray,
    feature_names: Sequence[str],
    *,
    background: np.ndarray | None = None,
    max_rows: int = MAX_SHAP_ROWS,
    max_background: int = MAX_SHAP_BACKGROUND,
    seed: int = 0,
) -> dict[str, Any]:
    """Return the mean absolute SHAP value of every feature.

    ``estimator`` must be a fitted tree estimator. The explained rows and the
    background set are subsampled deterministically, and the additivity property
    is verified for the explained rows.
    """
    import shap

    x = np.asarray(x, dtype=float)
    if x.shape[1] != len(feature_names):
        raise ValueError("Every feature needs a name.")
    rng = np.random.default_rng(seed)
    row_count = min(len(x), max_rows)
    row_index = (
        np.sort(rng.choice(len(x), size=row_count, replace=False))
        if row_count < len(x)
        else np.arange(len(x))
    )
    explained = x[row_index]

    background_rows = x
    if background is not None:
        background_rows = np.asarray(background, dtype=float)
    background_count = min(len(background_rows), max_background)
    if background_count < len(background_rows):
        background_index = np.sort(
            rng.choice(len(background_rows), size=background_count, replace=False)
        )
        background_rows = background_rows[background_index]

    explainer = shap.TreeExplainer(estimator, data=background_rows)
    values = np.asarray(explainer.shap_values(explained), dtype=float)
    if values.ndim == 3:  # (rows, features, classes) for multi-output models
        values = values[:, :, 0]
    mean_absolute = np.mean(np.abs(values), axis=0)

    # Additivity: the base value plus the SHAP values of a row must reproduce
    # the model's prediction for that row.
    base_value = float(np.asarray(explainer.expected_value).ravel()[0])
    predictions = np.asarray(estimator.predict(explained), dtype=float).reshape(-1)
    reconstructed = base_value + values.sum(axis=1)
    additivity_error = (
        float(np.max(np.abs(predictions - reconstructed))) if len(predictions) else 0.0
    )

    rows: list[dict[str, Any]] = [
        {
            "feature": name,
            "method": "shap",
            "value": float(mean_absolute[index]),
            "baseline": base_value,
            "unit": "mean absolute SHAP value",
            "detail": {
                "explained_rows": int(row_count),
                "background_rows": len(background_rows),
                "additivity_max_error": additivity_error,
            },
        }
        for index, name in enumerate(feature_names)
    ]
    ranked = sorted(rows, key=lambda row: float(row["value"]), reverse=True)
    for rank, row in enumerate(ranked, start=1):
        row["rank"] = rank
    return {"rows": ranked, "additivity_max_error": additivity_error}
