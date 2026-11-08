"""Public explainability exports.

The explainability layer reads a fitted model and the held-out rows and
produces renderer-neutral tables: permutation importance, SHAP values for the
tree ensembles, partial dependence, and the stability of an importance ranking
across folds, years, or sectors. A method that cannot be computed is recorded
as a limitation; it is never silently replaced by another method.
"""

from __future__ import annotations

from trendsmapp.explainability.effects import EFFECT_METHODS, partial_dependence_effects
from trendsmapp.explainability.payloads import (
    EXPLANATION_KINDS,
    ExplanationTable,
    FeatureImportance,
    ImportanceKind,
)
from trendsmapp.explainability.permutation import (
    DEFAULT_REPEATS,
    permutation_importance,
)
from trendsmapp.explainability.pipeline import explain_model
from trendsmapp.explainability.shap_values import (
    MAX_SHAP_BACKGROUND,
    MAX_SHAP_ROWS,
    SHAP_FAMILIES,
    shap_importance,
    supports_shap,
)
from trendsmapp.explainability.stability import importance_stability

__all__ = [
    "DEFAULT_REPEATS",
    "EFFECT_METHODS",
    "EXPLANATION_KINDS",
    "MAX_SHAP_BACKGROUND",
    "MAX_SHAP_ROWS",
    "SHAP_FAMILIES",
    "ExplanationTable",
    "FeatureImportance",
    "ImportanceKind",
    "explain_model",
    "importance_stability",
    "partial_dependence_effects",
    "permutation_importance",
    "shap_importance",
    "supports_shap",
]
