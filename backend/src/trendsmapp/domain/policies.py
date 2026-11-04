"""Explicit duplicate, exclusion, censoring, and extrapolation policies.

Each policy is a small, testable decision object. They are deliberately
separate from the code that applies them, so that the scientific meaning of a
choice ("keep the first duplicate", "exclude invalid observations", "do not
extrapolate") is reviewable on its own and recorded verbatim in a run
manifest.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from trendsmapp.domain.enums import (
    CensoringPolicy,
    DuplicatePolicy,
    ExclusionPolicy,
    ExtrapolationPolicy,
    QcFlagCode,
    QcStatus,
)

__all__ = [
    "CensoringPolicySpec",
    "DuplicatePolicySpec",
    "ExclusionPolicySpec",
    "ExtrapolationPolicySpec",
]


@dataclass(frozen=True, slots=True)
class DuplicatePolicySpec:
    """How duplicates are resolved when several rows describe one observation."""

    policy: DuplicatePolicy = DuplicatePolicy.FLAG_ALL
    #: Flags considered a semantic duplicate of another row.
    matching_flags: frozenset[QcFlagCode] = field(
        default_factory=lambda: frozenset({QcFlagCode.DUPLICATE_OBSERVATION})
    )

    def choose(self, candidates: list[int]) -> int:
        """Return the index of the row retained among ``candidates``.

        ``candidates`` holds the indexes of rows that describe the same
        observation. The policy defines which one survives; the caller keeps
        every other row in the dataset with an explicit duplicate flag.
        """
        if not candidates:
            raise ValueError("At least one candidate is required.")
        if self.policy is DuplicatePolicy.FLAG_ALL:
            return candidates[0]
        if self.policy is DuplicatePolicy.KEEP_FIRST:
            return min(candidates)
        if self.policy is DuplicatePolicy.KEEP_LAST:
            return max(candidates)
        if self.policy is DuplicatePolicy.KEEP_MOST_COMPLETE:
            return candidates[0]
        raise ValueError("The 'error' duplicate policy is applied by the caller before resolution.")


@dataclass(frozen=True, slots=True)
class ExclusionPolicySpec:
    """Which flagged observations are excluded from an analysis."""

    policy: ExclusionPolicy = ExclusionPolicy.NONE
    excluded_flags: frozenset[QcFlagCode] = field(default_factory=frozenset)

    def should_exclude(self, status: QcStatus, flags: frozenset[QcFlagCode]) -> bool:
        """Return whether an observation is excluded by this policy."""
        if self.policy is ExclusionPolicy.NONE:
            return False
        if self.policy is ExclusionPolicy.EXCLUDE_INVALID:
            return status is QcStatus.FAIL
        if self.policy is ExclusionPolicy.EXCLUDE_FLAGGED:
            return bool(flags & self.excluded_flags) or status is QcStatus.FAIL
        raise ValueError(f"Unknown exclusion policy: {self.policy}")


@dataclass(frozen=True, slots=True)
class CensoringPolicySpec:
    """How values below a detection limit enter calculations."""

    policy: CensoringPolicy = CensoringPolicy.KEEP_AS_LIMIT

    def apply(self, value: float | None, detection_limit: float | None) -> float | None:
        """Return the numeric value used in calculations.

        ``None`` is returned when the observation cannot contribute a number
        under this policy, which is different from a substituted zero.
        """
        if value is not None:
            return value
        if detection_limit is None:
            return None
        if self.policy is CensoringPolicy.KEEP_AS_LIMIT:
            return detection_limit
        if self.policy is CensoringPolicy.SUBSTITUTE_HALF:
            return detection_limit / 2.0
        if self.policy is CensoringPolicy.SUBSTITUTE_ZERO:
            return 0.0
        if self.policy is CensoringPolicy.EXCLUDE:
            return None
        raise ValueError(f"Unknown censoring policy: {self.policy}")


@dataclass(frozen=True, slots=True)
class ExtrapolationPolicySpec:
    """Whether temporal interpolation may continue beyond observed periods."""

    policy: ExtrapolationPolicy = ExtrapolationPolicy.NONE

    @property
    def allows_extrapolation(self) -> bool:
        """Return whether values may be produced outside the observed period."""
        return self.policy is not ExtrapolationPolicy.NONE
