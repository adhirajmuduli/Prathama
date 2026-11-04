"""Quality-control report models.

The QC report is a stored artifact document: it records which rules ran, what
they found, and how every flag was distributed, so a reviewer can audit a
dataset version without re-running anything. Flags are counts and capped
source-row lists, never file content.
"""

from __future__ import annotations

from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field

from trendsmapp.contracts.versions import APPLICATION_VERSION, ARTIFACT_SCHEMA_VERSION
from trendsmapp.domain.enums import QcFlagCode

__all__ = [
    "MAX_FLAG_SOURCE_ROWS",
    "QcFlagEntry",
    "QcParameterReport",
    "QcReport",
]

#: How many source rows are recorded per flag; the rest are counted.
MAX_FLAG_SOURCE_ROWS: Final[int] = 200


class QcFlagEntry(BaseModel):
    """One flag code with its count and a capped list of source rows."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: QcFlagCode
    count: int
    source_rows: tuple[int, ...] = ()
    detail: str | None = None


class QcParameterReport(BaseModel):
    """QC outcome for one parameter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    parameter_id: str
    observation_count: int
    flagged_count: int
    flag_counts: dict[str, int] = Field(default_factory=dict)


class QcReport(BaseModel):
    """The stored document describing one QC run over a dataset version."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = ARTIFACT_SCHEMA_VERSION
    application_version: str = APPLICATION_VERSION
    dataset_id: str
    dataset_version_id: str
    observation_count: int = 0
    flagged_count: int = 0
    pass_count: int = 0
    warning_count: int = 0
    fail_count: int = 0
    flags: tuple[QcFlagEntry, ...] = ()
    parameters: tuple[QcParameterReport, ...] = ()
    boundary_id: str | None = None
    rules_applied: tuple[str, ...] = ()
    rules_skipped: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    completed: bool = True

    def flag_counts(self) -> dict[str, int]:
        """Return the total count per flag code."""
        return {entry.code.value: entry.count for entry in self.flags}

    def to_summary_dict(self) -> dict[str, Any]:
        """Return a compact JSON-able summary."""
        return {
            "schema_version": self.schema_version,
            "dataset_id": self.dataset_id,
            "dataset_version_id": self.dataset_version_id,
            "observation_count": self.observation_count,
            "flagged_count": self.flagged_count,
            "pass_count": self.pass_count,
            "warning_count": self.warning_count,
            "fail_count": self.fail_count,
            "flags": self.flag_counts(),
            "rules_applied": list(self.rules_applied),
            "rules_skipped": list(self.rules_skipped),
        }
