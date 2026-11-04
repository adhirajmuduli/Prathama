"""Tests for recipe-controlled duplicate detection."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from trendsmapp.domain.enums import DuplicatePolicy
from trendsmapp.domain.policies import DuplicatePolicySpec
from trendsmapp.errors import ValidationError
from trendsmapp.normalization.duplicates import find_duplicates

T0 = datetime(2024, 1, 15, 9, 30, tzinfo=UTC)
T1 = datetime(2024, 2, 12, 9, 15, tzinfo=UTC)
KEY_A = ("st_a", "dissolved_oxygen", T0)
KEY_B = ("st_b", "salinity", T1)


def _entries(*specs: tuple[object, int, int]) -> list[tuple[object, int, int]]:
    return list(specs)


def test_rows_with_distinct_keys_are_not_duplicates() -> None:
    entries = _entries((KEY_A, 0, 3), (KEY_B, 1, 2))
    report = find_duplicates(entries, policy=DuplicatePolicySpec())
    assert report.groups == ()
    assert report.duplicate_row_indexes == frozenset()


def test_flag_all_retains_the_first_and_flags_the_rest() -> None:
    entries = _entries((KEY_A, 0, 1), (KEY_A, 1, 3), (KEY_A, 2, 2))
    report = find_duplicates(entries, policy=DuplicatePolicySpec(policy=DuplicatePolicy.FLAG_ALL))
    assert len(report.groups) == 1
    group = report.groups[0]
    assert group.key == KEY_A
    assert group.row_indexes == (0, 1, 2)
    assert group.retained_index == 0
    assert report.duplicate_row_indexes == frozenset({1, 2})


def test_keep_last_retains_the_last_row() -> None:
    entries = _entries((KEY_A, 0, 1), (KEY_A, 1, 1))
    report = find_duplicates(entries, policy=DuplicatePolicySpec(policy=DuplicatePolicy.KEEP_LAST))
    assert report.groups[0].retained_index == 1
    assert report.duplicate_row_indexes == frozenset({0})


def test_keep_first_retains_the_earliest_row() -> None:
    entries = _entries((KEY_A, 5, 1), (KEY_A, 2, 1))
    report = find_duplicates(entries, policy=DuplicatePolicySpec(policy=DuplicatePolicy.KEEP_FIRST))
    assert report.groups[0].retained_index == 2


def test_keep_most_complete_uses_the_completeness_score() -> None:
    entries = _entries((KEY_A, 0, 1), (KEY_A, 1, 5), (KEY_A, 2, 3))
    report = find_duplicates(
        entries, policy=DuplicatePolicySpec(policy=DuplicatePolicy.KEEP_MOST_COMPLETE)
    )
    assert report.groups[0].retained_index == 1
    assert report.duplicate_row_indexes == frozenset({0, 2})


def test_error_policy_refuses_duplicates() -> None:
    entries = _entries((KEY_A, 0, 1), (KEY_A, 1, 1))
    with pytest.raises(ValidationError) as error:
        find_duplicates(entries, policy=DuplicatePolicySpec(policy=DuplicatePolicy.ERROR))
    assert error.value.details["reason"] == "duplicate_observations"
    assert error.value.details["station"] == "st_a"


def test_detection_is_deterministic_in_first_seen_order() -> None:
    entries = _entries((KEY_B, 0, 1), (KEY_A, 1, 1), (KEY_B, 2, 1), (KEY_A, 3, 1))
    first = find_duplicates(entries, policy=DuplicatePolicySpec())
    second = find_duplicates(entries, policy=DuplicatePolicySpec())
    assert first == second
    assert [group.key for group in first.groups] == [KEY_B, KEY_A]
