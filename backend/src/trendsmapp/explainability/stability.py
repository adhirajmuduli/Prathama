"""Importance stability across folds, years, and sectors.

A ranking that changes completely between folds or sectors is not a finding;
it is noise. Two per-feature measures are reported:

* **rank stability** — one minus the normalized range of the feature's rank
  across the groups, so a feature that holds its position scores one and a
  feature that swaps between first and last scores zero;
* **direction agreement** — the share of groups in which the feature's
  importance keeps the same sign, so a feature that helps in one group and
  hurts in another is visible.

Both are computed from the recorded per-group importances, so a reader can
recompute them from the stored numbers.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = ["importance_stability"]


def importance_stability(
    importances_by_group: Mapping[str, Mapping[str, float]],
) -> list[dict[str, Any]]:
    """Return the rank and direction stability of every feature across groups.

    ``importances_by_group`` maps a group label (a fold, a year, or a sector)
    to the feature importances measured in that group.
    """
    groups = sorted(importances_by_group)
    if len(groups) < 2:
        return []
    features = sorted({name for group in groups for name in importances_by_group[group]})
    rows: list[dict[str, Any]] = []
    for feature in features:
        ranks: list[int] = []
        signs: list[float] = []
        for group in groups:
            values = importances_by_group[group]
            if feature not in values:
                continue
            ordered = sorted(values, key=lambda name: float(values[name]), reverse=True)
            ranks.append(ordered.index(feature) + 1)
            signs.append(1.0 if float(values[feature]) >= 0 else -1.0)
        if len(ranks) < 2:
            continue
        rank_span = max(ranks) - min(ranks)
        normalized_span = rank_span / (len(ranks) - 1)
        rank_stability = 1.0 - normalized_span
        positive = sum(1 for sign in signs if sign > 0)
        negative = len(signs) - positive
        direction_agreement = max(positive, negative) / len(signs)
        rows.append(
            {
                "feature": feature,
                "method": "stability",
                "value": float(rank_stability),
                "baseline": None,
                "unit": "rank stability across groups (1 = unchanged rank)",
                "detail": {
                    "groups": len(ranks),
                    "rank_min": int(min(ranks)),
                    "rank_max": int(max(ranks)),
                    "direction_agreement": float(direction_agreement),
                },
            }
        )
    ranked = sorted(rows, key=lambda row: float(row["value"]), reverse=True)
    for rank, row in enumerate(ranked, start=1):
        row["rank"] = rank
    return ranked
