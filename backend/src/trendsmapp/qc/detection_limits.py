"""Detection-limit consistency checks.

A censored value carries the limit it was censored at, in canonical units. Two
things are checked: the limit the file reports against the limit the registry
declares for the parameter (``detection_limit_mismatch``), and whether one
parameter carries several different limits across rows
(``detection_limit_inconsistent``). Both are flags; the values stay in the
dataset.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from trendsmapp.domain.enums import QcFlagCode
from trendsmapp.domain.models import Observation
from trendsmapp.qc.ranges import QcRanges

__all__ = ["check_detection_limits"]

#: Relative tolerance when comparing two detection limits.
_LIMIT_TOLERANCE: float = 1e-9


def check_detection_limits(
    observations: Sequence[Observation],
    ranges: QcRanges,
) -> list[tuple[int, QcFlagCode]]:
    """Flag censored observations whose detection limit disagrees with the registry.

    A limit that differs from the declared one by more than a relative
    tolerance is a mismatch. A parameter whose rows carry more than one
    distinct limit is inconsistent, and every row of that parameter carrying a
    limit is flagged.
    """
    findings: list[tuple[int, QcFlagCode]] = []
    by_parameter: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for index, observation in enumerate(observations):
        if observation.detection_limit is None or not observation.parameter_id:
            continue
        declared = ranges.detection_limit(observation.parameter_id)
        if declared is not None and not _same_limit(observation.detection_limit, declared):
            findings.append((index, QcFlagCode.DETECTION_LIMIT_MISMATCH))
        by_parameter[observation.parameter_id].append((index, observation.detection_limit))

    for _parameter_id, entries in by_parameter.items():
        distinct = {limit for _, limit in entries}
        if len(distinct) > 1:
            for index, _ in entries:
                findings.append((index, QcFlagCode.DETECTION_LIMIT_INCONSISTENT))
    return findings


def _same_limit(left: float, right: float) -> bool:
    """Return whether two limits agree within a relative tolerance."""
    scale = max(abs(left), abs(right), 1.0)
    return abs(left - right) <= _LIMIT_TOLERANCE * scale
