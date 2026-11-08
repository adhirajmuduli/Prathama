"""Explain a fitted model with the methods the model and the task support.

Only the requested methods are computed, and only when the model supports
them. A method that cannot be computed is recorded as a limitation; the run
never substitutes a different method for the one that was asked for, because a
number with a different meaning is worse than a recorded absence.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import numpy as np

from trendsmapp.domain.enums import ExplanationMethod, ModelFamily
from trendsmapp.explainability.effects import partial_dependence_effects
from trendsmapp.explainability.payloads import ExplanationTable, FeatureImportance
from trendsmapp.explainability.permutation import permutation_importance
from trendsmapp.explainability.shap_values import shap_importance, supports_shap
from trendsmapp.explainability.stability import importance_stability

__all__ = ["explain_model"]


def explain_model(
    *,
    family: ModelFamily,
    predict: Callable[[np.ndarray], np.ndarray],
    x: np.ndarray,
    y: np.ndarray,
    feature_names: Sequence[str],
    methods: Sequence[ExplanationMethod],
    estimator: Any = None,
    background: np.ndarray | None = None,
    groups: Sequence[str] | None = None,
    seed: int = 0,
    primary_metric: str = "rmse",
    repeats: int = 10,
) -> ExplanationTable:
    """Compute the requested explanations for a fitted model."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float).reshape(-1)
    rows: list[FeatureImportance] = []
    limitations: list[str] = []

    for method in methods:
        if method is ExplanationMethod.PERMUTATION:
            for row in permutation_importance(
                predict,
                x,
                y,
                feature_names,
                repeats=repeats,
                seed=seed,
                primary_metric=primary_metric,
            ):
                rows.append(_to_importance(row))
        elif method is ExplanationMethod.SHAP_TREE:
            if estimator is None:
                limitations.append(
                    "shap_tree requires the fitted estimator, which was not provided"
                )
            elif not supports_shap(family):
                limitations.append(f"shap_tree is not supported for model family '{family.value}'")
            else:
                result = shap_importance(
                    estimator,
                    x,
                    feature_names,
                    background=background,
                    seed=seed,
                )
                for row in result["rows"]:
                    rows.append(_to_importance(row))
                if result["additivity_max_error"] > 1e-4:
                    limitations.append(
                        "the SHAP additivity check exceeded the tolerance: "
                        f"{result['additivity_max_error']:.3g}"
                    )
        elif method is ExplanationMethod.PARTIAL_DEPENDENCE:
            if estimator is None:
                limitations.append(
                    "partial_dependence requires the fitted estimator, which was not provided"
                )
            else:
                result = partial_dependence_effects(estimator, x, feature_names, family=family)
                for row in result["rows"]:
                    rows.append(_to_importance(row))
                limitations.extend(result["limitations"])
        else:
            limitations.append(  # type: ignore[unreachable]
                f"unknown explanation method '{getattr(method, 'value', method)}'"
            )

    if groups is not None and len(set(groups)) > 1:
        importances_by_group: dict[str, dict[str, float]] = {}
        for group in sorted(set(groups)):
            index = [i for i, value in enumerate(groups) if value == group]
            group_x = x[index]
            group_y = y[index]
            importances_by_group[group] = {
                row["feature"]: float(row["value"])
                for row in permutation_importance(
                    predict,
                    group_x,
                    group_y,
                    feature_names,
                    repeats=max(2, repeats // 2),
                    seed=seed,
                    primary_metric=primary_metric,
                )
            }
        for row in importance_stability(importances_by_group):
            rows.append(_to_importance(row))

    ordered = sorted(
        rows,
        key=lambda row: (row.method, -float(row.value), row.feature),
    )
    return ExplanationTable(
        model_family=family.value,
        method="mixed"
        if len({row.method for row in ordered}) > 1
        else (ordered[0].method if ordered else "none"),
        rows=tuple(ordered),
        limitations=tuple(dict.fromkeys(limitations)),
        detail={
            "features": list(feature_names),
            "rows": len(x),
            "primary_metric": primary_metric,
            "seed": seed,
        },
    )


def _to_importance(row: dict[str, Any]) -> FeatureImportance:
    """Convert a raw importance row into the payload type."""
    return FeatureImportance(
        feature=str(row["feature"]),
        method=str(row["method"]),
        value=float(row["value"]),
        baseline=row.get("baseline"),
        unit=row.get("unit"),
        group=row.get("group"),
        rank=row.get("rank"),
        detail=dict(row.get("detail") or {}),
    )
