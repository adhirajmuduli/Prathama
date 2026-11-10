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


def _explain_permutation(**kwargs: Any) -> tuple[list[FeatureImportance], list[str]]:
    """Permutation importance rows."""
    rows = [
        _to_importance(row)
        for row in permutation_importance(
            kwargs["predict"],
            kwargs["x"],
            kwargs["y"],
            kwargs["feature_names"],
            repeats=kwargs["repeats"],
            seed=kwargs["seed"],
            primary_metric=kwargs["primary_metric"],
        )
    ]
    return rows, []


def _explain_shap(**kwargs: Any) -> tuple[list[FeatureImportance], list[str]]:
    """SHAP tree rows, with an additivity self-check."""
    family = kwargs["family"]
    estimator = kwargs["estimator"]
    if estimator is None:
        return [], ["shap_tree requires the fitted estimator, which was not provided"]
    if not supports_shap(family):
        return [], [f"shap_tree is not supported for model family '{family.value}'"]
    result = shap_importance(
        estimator,
        kwargs["x"],
        kwargs["feature_names"],
        background=kwargs["background"],
        seed=kwargs["seed"],
    )
    rows = [_to_importance(row) for row in result["rows"]]
    limitations: list[str] = []
    if result["additivity_max_error"] > 1e-4:
        limitations.append(
            "the SHAP additivity check exceeded the tolerance: "
            f"{result['additivity_max_error']:.3g}"
        )
    return rows, limitations


def _explain_partial_dependence(**kwargs: Any) -> tuple[list[FeatureImportance], list[str]]:
    """Partial-dependence rows and their recorded limitations."""
    estimator = kwargs["estimator"]
    if estimator is None:
        return [], ["partial_dependence requires the fitted estimator, which was not provided"]
    result = partial_dependence_effects(
        estimator, kwargs["x"], kwargs["feature_names"], family=kwargs["family"]
    )
    return [_to_importance(row) for row in result["rows"]], list(result["limitations"])


_EXPLAINERS: dict[ExplanationMethod, Callable[..., tuple[list[FeatureImportance], list[str]]]] = {
    ExplanationMethod.PERMUTATION: _explain_permutation,
    ExplanationMethod.SHAP_TREE: _explain_shap,
    ExplanationMethod.PARTIAL_DEPENDENCE: _explain_partial_dependence,
}


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
        method_rows, method_limitations = _EXPLAINERS[method](
            family=family,
            predict=predict,
            x=x,
            y=y,
            feature_names=feature_names,
            estimator=estimator,
            background=background,
            seed=seed,
            primary_metric=primary_metric,
            repeats=repeats,
        )
        rows.extend(method_rows)
        limitations.extend(method_limitations)

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
