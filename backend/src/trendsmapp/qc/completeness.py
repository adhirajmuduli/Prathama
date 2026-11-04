"""Completeness checks: missing values, timestamps, and sectors.

Completeness counts what is absent and flags it; it never fills anything in.
A missing value, a missing timestamp, and a missing sector are three different
flags, because they mean three different things to an analyst.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from trendsmapp.domain.enums import QcFlagCode
from trendsmapp.domain.models import Observation

__all__ = ["CompletenessSummary", "check_completeness"]


class CompletenessSummary:
    """Accumulated completeness counts, built by :func:`check_completeness`."""

    def __init__(self) -> None:
        self.by_parameter: dict[str, dict[str, int]] = defaultdict(
            lambda: {"total": 0, "missing_value": 0, "missing_timestamp": 0, "missing_sector": 0}
        )
        self.total = 0

    def record(
        self,
        parameter_id: str,
        *,
        missing_value: bool,
        missing_timestamp: bool,
        missing_sector: bool,
    ) -> None:
        """Record one observation's completeness state."""
        entry = self.by_parameter[parameter_id]
        entry["total"] += 1
        self.total += 1
        if missing_value:
            entry["missing_value"] += 1
        if missing_timestamp:
            entry["missing_timestamp"] += 1
        if missing_sector:
            entry["missing_sector"] += 1


def check_completeness(
    observations: Sequence[Observation],
    *,
    sectors_required: bool = False,
) -> tuple[list[tuple[int, QcFlagCode]], CompletenessSummary]:
    """Flag missing values, timestamps, and sectors.

    Returns the findings and the accumulated summary. ``sectors_required``
    comes from the analysis recipe: when the study declares sectors, an
    observation without one is flagged ``missing_sector``.
    """
    findings: list[tuple[int, QcFlagCode]] = []
    summary = CompletenessSummary()
    for index, observation in enumerate(observations):
        parameter_id = observation.parameter_id or "unknown"
        missing_value = (
            observation.raw_value is not None
            and observation.canonical_value is None
            and observation.detection_limit is None
        ) or observation.raw_value is None
        missing_timestamp = False  # unparsable timestamps were skipped at canonicalization
        missing_sector = sectors_required and observation.sector is None
        summary.record(
            parameter_id,
            missing_value=missing_value,
            missing_timestamp=missing_timestamp,
            missing_sector=missing_sector,
        )
        if missing_value:
            findings.append((index, QcFlagCode.MISSING_VALUE))
        if missing_sector:
            findings.append((index, QcFlagCode.MISSING_SECTOR))
    return findings, summary
