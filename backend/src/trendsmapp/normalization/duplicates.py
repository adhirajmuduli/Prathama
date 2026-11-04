"""Recipe-controlled duplicate detection across station, parameter, and time.

Two rows describe the same observation when they agree on station, parameter,
and timestamp. The duplicate policy — declared in the column mapping — decides
which row is retained; every other row stays in the dataset with an explicit
duplicate flag. The ``error`` policy refuses to resolve duplicates at all and
fails the run, because silently choosing a value is exactly what it forbids.

Detection is deterministic: groups are keyed in first-seen order, and the
retained row is chosen by the declared policy, never by iteration order of a
hash table.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from trendsmapp.domain.enums import DuplicatePolicy
from trendsmapp.domain.policies import DuplicatePolicySpec
from trendsmapp.errors import ValidationError

__all__ = [
    "DuplicateGroup",
    "DuplicateReport",
    "find_duplicates",
]

#: The identity of one observation for duplicate purposes.
ObservationKey = tuple[str, str, datetime]


@dataclass(frozen=True, slots=True)
class DuplicateGroup:
    """One set of rows that describe the same observation."""

    key: ObservationKey
    row_indexes: tuple[int, ...]
    retained_index: int


@dataclass(frozen=True, slots=True)
class DuplicateReport:
    """The outcome of duplicate detection over a set of rows."""

    groups: tuple[DuplicateGroup, ...]

    @property
    def duplicate_row_indexes(self) -> frozenset[int]:
        """Return every row that is not the retained member of its group."""
        return frozenset(
            index
            for group in self.groups
            for index in group.row_indexes
            if index != group.retained_index
        )


def find_duplicates(
    entries: Sequence[tuple[ObservationKey, int, int]],
    *,
    policy: DuplicatePolicySpec,
) -> DuplicateReport:
    """Group rows by observation key and choose the retained row per group.

    Each entry is ``(key, row_index, completeness)``, where completeness is the
    number of populated canonical fields of that row. Rows without a complete
    key cannot be duplicates of anything and are not passed here.
    """
    grouped: OrderedDict[ObservationKey, list[int]] = OrderedDict()
    completeness: dict[int, int] = {}
    for key, row_index, row_completeness in entries:
        grouped.setdefault(key, []).append(row_index)
        completeness[row_index] = row_completeness

    if policy.policy is DuplicatePolicy.ERROR and any(
        len(indexes) > 1 for indexes in grouped.values()
    ):
        offender = next(key for key, indexes in grouped.items() if len(indexes) > 1)
        raise ValidationError(
            "Duplicate observations are present and the declared duplicate policy is 'error'.",
            details={
                "reason": "duplicate_observations",
                "station": offender[0],
                "parameter": offender[1],
                "sampled_at": offender[2].isoformat(),
            },
        )

    groups: list[DuplicateGroup] = []
    for key, indexes in grouped.items():
        if len(indexes) < 2:
            continue
        if policy.policy is DuplicatePolicy.KEEP_MOST_COMPLETE:
            retained = max(
                indexes,
                key=lambda index: (completeness.get(index, 0), -index),
            )
        else:
            retained = policy.choose(list(indexes))
        groups.append(
            DuplicateGroup(
                key=key,
                row_indexes=tuple(indexes),
                retained_index=retained,
            )
        )
    return DuplicateReport(groups=tuple(groups))
