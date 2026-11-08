"""Renderer-neutral explanation payloads.

An explanation is a table of named values, not a picture. The frontend and the
report renderer both consume these tables, so the same numbers can appear in a
figure, a table, and an export without a second computation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final

__all__ = [
    "EXPLANATION_KINDS",
    "ExplanationTable",
    "FeatureImportance",
    "ImportanceKind",
]

ImportanceKind: Final[str] = "importance"

#: The kinds of explanation value the payload can carry.
EXPLANATION_KINDS: Final[tuple[str, ...]] = (
    "importance",
    "shap",
    "effect",
    "stability",
)


@dataclass(frozen=True, slots=True)
class FeatureImportance:
    """One feature's importance under one method."""

    feature: str
    method: str
    #: Signed importance in the metric of the model run (RMSE by default).
    value: float
    #: The metric value without the feature's contribution, when known.
    baseline: float | None = None
    unit: str | None = None
    group: str | None = None
    rank: int | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def as_payload(self) -> dict[str, Any]:
        """Return the JSON-able payload of one importance."""
        return {
            "feature": self.feature,
            "method": self.method,
            "value": self.value,
            "baseline": self.baseline,
            "unit": self.unit,
            "group": self.group,
            "rank": self.rank,
            "detail": dict(self.detail),
        }


@dataclass(frozen=True, slots=True)
class ExplanationTable:
    """A complete explanation for one model run."""

    model_family: str
    method: str
    rows: tuple[FeatureImportance, ...]
    #: Limitations the run recorded, for example an unsupported method.
    limitations: tuple[str, ...] = ()
    detail: dict[str, Any] = field(default_factory=dict)

    def as_payload(self) -> dict[str, Any]:
        """Return the JSON-able payload of the table."""
        return {
            "model_family": self.model_family,
            "method": self.method,
            "rows": [row.as_payload() for row in self.rows],
            "limitations": list(self.limitations),
            "detail": dict(self.detail),
        }
