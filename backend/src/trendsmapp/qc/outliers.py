"""Robust outlier detection per station and parameter.

The modified z-score is used because it survives the outliers it is looking
for: ``M_i = 0.6745 * (x_i - median) / MAD``, flagged when ``|M_i| > 3.5``.
Groups with fewer than five values, or with a zero MAD (all values equal, or
too little spread to measure), are skipped and reported, not guessed at.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Sequence
from typing import Final

from trendsmapp.domain.enums import QcFlagCode
from trendsmapp.domain.models import Observation

__all__ = ["MIN_GROUP_SIZE", "MODIFIED_Z_THRESHOLD", "check_outliers"]

#: Smallest group size that supports a robust outlier decision.
MIN_GROUP_SIZE: Final[int] = 5

#: Modified z-score above which a value is an outlier.
MODIFIED_Z_THRESHOLD: Final[float] = 3.5

#: Constant of the modified z-score (median absolute deviation scaling).
_MAD_SCALE: Final[float] = 0.6745


def check_outliers(
    observations: Sequence[Observation],
    *,
    min_group_size: int = MIN_GROUP_SIZE,
    threshold: float = MODIFIED_Z_THRESHOLD,
) -> tuple[list[tuple[int, QcFlagCode]], list[str]]:
    """Flag robust outliers within each (station, parameter) group.

    Returns the findings and a list of skipped-group notes. Only observations
    with a canonical value participate.
    """
    groups: dict[tuple[str, str], list[tuple[int, float]]] = defaultdict(list)
    for index, observation in enumerate(observations):
        if observation.canonical_value is None or not observation.parameter_id:
            continue
        groups[(observation.station_label or "", observation.parameter_id)].append(
            (index, observation.canonical_value)
        )

    findings: list[tuple[int, QcFlagCode]] = []
    skipped: list[str] = []
    for (station, parameter_id), entries in sorted(groups.items()):
        if len(entries) < min_group_size:
            skipped.append(
                f"group {station}/{parameter_id} has {len(entries)} values; "
                f"outlier detection needs at least {min_group_size}"
            )
            continue
        values = [value for _, value in entries]
        median = statistics.median(values)
        mad = statistics.median([abs(value - median) for value in values])
        if mad == 0:
            if len(set(values)) > 1:
                skipped.append(
                    f"group {station}/{parameter_id} has zero MAD with distinct "
                    "values; outlier detection skipped"
                )
            continue
        for index, value in entries:
            score = _MAD_SCALE * (value - median) / mad
            if abs(score) > threshold:
                findings.append((index, QcFlagCode.OUTLIER_ROBUST))
    return findings, skipped
