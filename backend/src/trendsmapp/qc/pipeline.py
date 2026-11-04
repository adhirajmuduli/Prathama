"""The QC pipeline: run every rule, apply flags, and produce the report.

Quality control never deletes anything. Each rule returns findings as
``(observation_index, flag)`` pairs (plus optional detail); the pipeline folds
them into the observations' ``qc_flags`` and computes ``qc_status`` from the
flag severity. The report records which rules ran, which were skipped and why,
and the distribution of every flag.
"""

from __future__ import annotations

import dataclasses
from collections import defaultdict
from collections.abc import Sequence
from typing import Final

from trendsmapp.domain.enums import QcFlagCode, QcStatus
from trendsmapp.domain.models import Observation
from trendsmapp.qc.completeness import CompletenessSummary, check_completeness
from trendsmapp.qc.coordinates import Boundary, check_coordinates, load_boundary
from trendsmapp.qc.detection_limits import check_detection_limits
from trendsmapp.qc.duplicates import check_duplicate_locations
from trendsmapp.qc.models import MAX_FLAG_SOURCE_ROWS, QcFlagEntry, QcParameterReport, QcReport
from trendsmapp.qc.outliers import check_outliers
from trendsmapp.qc.ranges import QcRanges, check_ranges, get_qc_ranges
from trendsmapp.qc.temporal import check_temporal

__all__ = [
    "FAIL_FLAGS",
    "QcPipeline",
    "QcResult",
]

#: Flags that make an observation unusable as a measurement.
FAIL_FLAGS: Final[frozenset[QcFlagCode]] = frozenset(
    {
        QcFlagCode.NON_FINITE_VALUE,
        QcFlagCode.MISSING_TIMESTAMP,
        QcFlagCode.IMPOSSIBLE_TIMESTAMP,
        QcFlagCode.INVALID_COORDINATE,
        QcFlagCode.COORDINATE_OUT_OF_RANGE,
        QcFlagCode.UNKNOWN_PARAMETER,
        QcFlagCode.UNKNOWN_UNIT,
        QcFlagCode.INCOMPATIBLE_UNIT,
    }
)


class QcResult:
    """The outcome of one QC run."""

    def __init__(self, observations: tuple[Observation, ...], report: QcReport) -> None:
        self.observations = observations
        self.report = report


class QcPipeline:
    """Runs the QC rules over canonical observations."""

    def __init__(
        self,
        *,
        dataset_id: str,
        dataset_version_id: str,
        ranges: QcRanges | None = None,
        boundary: Boundary | None = None,
        sectors_required: bool = False,
        use_boundary: bool = True,
    ) -> None:
        self._dataset_id = dataset_id
        self._dataset_version_id = dataset_version_id
        self._ranges = ranges
        self._boundary = boundary
        self._sectors_required = sectors_required
        self._use_boundary = use_boundary

    def run(self, observations: Sequence[Observation]) -> QcResult:
        """Apply every rule and build the report."""
        ranges = self._ranges or get_qc_ranges()
        boundary = self._boundary
        if boundary is None and self._use_boundary:
            boundary = load_boundary()

        findings: list[tuple[int, QcFlagCode, str | None]] = []
        rules_applied: list[str] = []
        rules_skipped: list[str] = []
        warnings: list[str] = []

        findings.extend((index, flag, None) for index, flag in check_ranges(observations, ranges))
        rules_applied.append("ranges")

        findings.extend(
            (index, flag, None) for index, flag in check_detection_limits(observations, ranges)
        )
        rules_applied.append("detection_limits")

        completeness_findings, summary = check_completeness(
            observations, sectors_required=self._sectors_required
        )
        findings.extend((index, flag, None) for index, flag in completeness_findings)
        rules_applied.append("completeness")

        findings.extend(
            (index, flag, None) for index, flag in check_duplicate_locations(observations)
        )
        rules_applied.append("duplicate_locations")

        if boundary is not None:
            findings.extend(
                (index, flag, detail)
                for index, flag, detail in check_coordinates(observations, boundary)
            )
            rules_applied.append("boundary_and_drift")
        else:
            rules_skipped.append("boundary_and_drift: no boundary configured")

        outlier_findings, outlier_notes = check_outliers(observations)
        findings.extend((index, flag, None) for index, flag in outlier_findings)
        rules_applied.append("outliers")
        warnings.extend(outlier_notes)

        temporal_findings, temporal_notes = check_temporal(observations)
        findings.extend(temporal_findings)
        rules_applied.append("temporal")
        warnings.extend(temporal_notes)

        observations_with_flags = self._apply(observations, findings)
        report = self._build_report(
            observations_with_flags,
            findings,
            summary,
            rules_applied,
            rules_skipped,
            warnings,
            boundary,
        )
        return QcResult(observations=tuple(observations_with_flags), report=report)

    def _apply(
        self,
        observations: Sequence[Observation],
        findings: list[tuple[int, QcFlagCode, str | None]],
    ) -> list[Observation]:
        """Fold findings into the observations' flags and status."""
        by_index: dict[int, list[QcFlagCode]] = defaultdict(list)
        for index, flag, _detail in findings:
            by_index[index].append(flag)
        rebuilt: list[Observation] = []
        for index, observation in enumerate(observations):
            flags = by_index.get(index, [])
            if not flags:
                rebuilt.append(observation)
                continue
            merged = tuple(dict.fromkeys((*observation.qc_flags, *flags)))
            status = self._status_for(merged)
            rebuilt.append(dataclasses.replace(observation, qc_flags=merged, qc_status=status))
        return rebuilt

    def _status_for(self, flags: tuple[QcFlagCode, ...]) -> QcStatus:
        """Return the status implied by a set of flags."""
        if any(flag in FAIL_FLAGS for flag in flags):
            return QcStatus.FAIL
        if flags:
            return QcStatus.WARNING
        return QcStatus.PASS

    def _build_report(
        self,
        observations: Sequence[Observation],
        findings: list[tuple[int, QcFlagCode, str | None]],
        summary: CompletenessSummary,
        rules_applied: list[str],
        rules_skipped: list[str],
        warnings: list[str],
        boundary: Boundary | None,
    ) -> QcReport:
        """Build the QC report document from the applied flags."""
        counts: dict[QcFlagCode, list[int]] = defaultdict(list)
        details: dict[QcFlagCode, str | None] = {}
        for index, flag, detail in findings:
            counts[flag].append(observations[index].source_row)
            if detail:
                details.setdefault(flag, detail)
        flag_entries = tuple(
            QcFlagEntry(
                code=flag,
                count=len(rows),
                source_rows=tuple(sorted(set(rows))[:MAX_FLAG_SOURCE_ROWS]),
                detail=details.get(flag),
            )
            for flag, rows in sorted(counts.items(), key=lambda item: item[0].value)
        )

        per_parameter: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "flagged": 0})
        per_parameter_flags: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        flagged_indexes = {index for index, _, _ in findings}
        for index, observation in enumerate(observations):
            parameter_id = observation.parameter_id or "unknown"
            entry = per_parameter[parameter_id]
            entry["total"] += 1
            if index in flagged_indexes:
                entry["flagged"] += 1
        for index, flag, _detail in findings:
            parameter_id = observations[index].parameter_id or "unknown"
            per_parameter_flags[parameter_id][flag.value] += 1
        parameter_entries = tuple(
            QcParameterReport(
                parameter_id=parameter_id,
                observation_count=entry["total"],
                flagged_count=entry["flagged"],
                flag_counts=dict(per_parameter_flags.get(parameter_id, {})),
            )
            for parameter_id, entry in sorted(per_parameter.items())
        )

        pass_count = sum(1 for o in observations if o.qc_status is QcStatus.PASS)
        warning_count = sum(1 for o in observations if o.qc_status is QcStatus.WARNING)
        fail_count = sum(1 for o in observations if o.qc_status is QcStatus.FAIL)
        return QcReport(
            dataset_id=self._dataset_id,
            dataset_version_id=self._dataset_version_id,
            observation_count=len(observations),
            flagged_count=len(flagged_indexes),
            pass_count=pass_count,
            warning_count=warning_count,
            fail_count=fail_count,
            flags=flag_entries,
            parameters=parameter_entries,
            boundary_id=boundary.boundary_id if boundary is not None else None,
            rules_applied=tuple(rules_applied),
            rules_skipped=tuple(rules_skipped),
            warnings=tuple(warnings),
        )
