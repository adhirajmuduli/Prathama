"""The factual methods record of a run, derived only from the stored recipe.

The record states what was actually executed — methods, splits, budgets,
seeds — and nothing else. It never interprets results and never claims
causality.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from trendsmapp.contracts.versions import APPLICATION_VERSION, ARTIFACT_SCHEMA_VERSION

__all__ = ["methods_record"]


def methods_record(recipe: Mapping[str, Any]) -> dict[str, Any]:
    """Build the methods record from one stored recipe or ML task document."""
    spatial = recipe.get("spatial")
    temporal = recipe.get("temporal")
    record: dict[str, Any] = {
        "application_version": APPLICATION_VERSION,
        "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        "seed": recipe.get("seed"),
        "spatial": None,
        "temporal": None,
        "machine_learning": None,
    }
    if isinstance(spatial, Mapping):
        methods = spatial.get("methods")
        record["spatial"] = {
            "methods": [method.get("method") for method in methods if isinstance(method, Mapping)]
            if isinstance(methods, list)
            else [],
            "analysis_crs": spatial.get("analysis_crs"),
            "grid_resolution_m": spatial.get("grid_resolution_m"),
            "validation": spatial.get("validation"),
            "selection_rule": spatial.get("selection_rule"),
            "permitted_qc_statuses": list(spatial.get("permitted_qc_statuses") or []),
        }
    if isinstance(temporal, Mapping):
        record["temporal"] = {
            "resolution": temporal.get("resolution"),
            "interpolation": temporal.get("interpolation"),
            "max_gap_days": temporal.get("max_gap_days"),
            "compute_trends": temporal.get("compute_trends"),
            "compute_change_points": temporal.get("compute_change_points"),
        }
    if "candidate_models" in recipe:
        record["machine_learning"] = {
            "target_parameter_id": recipe.get("target_parameter_id"),
            "prediction_unit": recipe.get("prediction_unit"),
            "setting": _value(recipe.get("setting")),
            "outer_split": _value(recipe.get("outer_split")),
            "inner_split": _value(recipe.get("inner_split")),
            "candidate_models": [_value(m) for m in recipe.get("candidate_models") or []],
            "search_budget": recipe.get("search_budget"),
            "primary_metric": recipe.get("primary_metric"),
            "qc_policy": recipe.get("qc_policy"),
            "lag_policy": recipe.get("lag_policy"),
            "uncertainty_method": _value(recipe.get("uncertainty_method")),
            "explanation_methods": [_value(m) for m in recipe.get("explanation_methods") or []],
        }
    return record


def _value(item: Any) -> Any:
    """Return the enum value of a stored enum, or the raw value."""
    return getattr(item, "value", item)
