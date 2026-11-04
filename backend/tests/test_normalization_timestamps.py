"""Tests for timestamp normalization under declared policies."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from trendsmapp.domain.enums import DateOrder, TimezonePolicy
from trendsmapp.errors import ValidationError
from trendsmapp.normalization.timestamps import apply_timezone_policy, parse_timestamp

DAY_FIRST = DateOrder.DAY_FIRST
MONTH_FIRST = DateOrder.MONTH_FIRST


def _parse(
    text: str,
    *,
    order: DateOrder = DAY_FIRST,
    policy: TimezonePolicy = TimezonePolicy.ASSUME_UTC,
    tz: str | None = None,
) -> datetime:
    return parse_timestamp(text, date_order=order, timezone_policy=policy, timezone_name=tz)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2024-01-15T09:30:00Z", "2024-01-15T09:30:00+00:00"),
        ("2024-01-15 09:30:00", "2024-01-15T09:30:00+00:00"),
        ("2024-01-15 09:30", "2024-01-15T09:30:00+00:00"),
        ("2024-01-15", "2024-01-15T00:00:00+00:00"),
        ("2024-02-29", "2024-02-29T00:00:00+00:00"),
        ("2024-01-15T09:30:00.123456Z", "2024-01-15T09:30:00.123456+00:00"),
        ("15/01/2024", "2024-01-15T00:00:00+00:00"),
        ("2024/01/15", "2024-01-15T00:00:00+00:00"),
        ("15-01-2024 09:30:00", "2024-01-15T09:30:00+00:00"),
        ("15.01.2024", "2024-01-15T00:00:00+00:00"),
        ("15 Jan 2024", "2024-01-15T00:00:00+00:00"),
        ("Jan 15, 2024", "2024-01-15T00:00:00+00:00"),
        ("January 15 2024", "2024-01-15T00:00:00+00:00"),
        ("2024 Jan 15", "2024-01-15T00:00:00+00:00"),
    ],
)
def test_parse_timestamp_accepts_unambiguous_forms(text: str, expected: str) -> None:
    assert _parse(text).isoformat() == expected


def test_parse_timestamp_converts_offsets_to_utc() -> None:
    result = _parse("2024-01-15T14:30:00+05:30", policy=TimezonePolicy.REQUIRE_OFFSET)
    assert result.isoformat() == "2024-01-15T09:00:00+00:00"
    assert result.tzinfo is UTC


def test_parse_timestamp_applies_the_declared_date_order() -> None:
    assert _parse("03/04/2024", order=DAY_FIRST).isoformat() == "2024-04-03T00:00:00+00:00"
    assert _parse("03/04/2024", order=MONTH_FIRST).isoformat() == "2024-03-04T00:00:00+00:00"


def test_parse_timestamp_rejects_values_impossible_under_the_declared_order() -> None:
    with pytest.raises(ValidationError) as error:
        _parse("25/12/2024", order=MONTH_FIRST)
    assert error.value.details["reason"] == "invalid_date"


def test_parse_timestamp_disambiguates_by_magnitude_when_the_year_is_not_first() -> None:
    assert _parse("2024-01-25", order=DAY_FIRST).isoformat() == "2024-01-25T00:00:00+00:00"
    assert _parse("25/2024/01", order=DAY_FIRST).day == 25


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("", "empty_timestamp"),
        ("2024", "partial_date"),
        ("2024-01", "partial_date"),
        ("45292", "numeric_timestamp"),
        ("45292.5", "numeric_timestamp"),
        ("24/02/24", "ambiguous_year"),
        ("13/13/2024", "invalid_date"),
        ("2024-02-30", "invalid_date"),
        ("32/01/2024", "invalid_date"),
        ("not a date", "unparsable_timestamp"),
        ("15 Foo 2024", "unparsable_timestamp"),
    ],
)
def test_parse_timestamp_rejects_ambiguous_or_invalid_values(text: str, reason: str) -> None:
    with pytest.raises(ValidationError) as error:
        _parse(text)
    assert error.value.details["reason"] == reason


def test_parse_timestamp_require_offset_rejects_naive_values() -> None:
    with pytest.raises(ValidationError) as error:
        _parse("2024-01-15T09:30:00", policy=TimezonePolicy.REQUIRE_OFFSET)
    assert error.value.details["reason"] == "missing_offset"


def test_parse_timestamp_named_policy_uses_the_named_zone() -> None:
    result = _parse("2024-01-15T09:30:00", policy=TimezonePolicy.NAMED, tz="Asia/Kolkata")
    assert result.isoformat() == "2024-01-15T04:00:00+00:00"


def test_parse_timestamp_named_policy_rejects_an_unknown_zone() -> None:
    with pytest.raises(ValidationError) as error:
        _parse("2024-01-15T09:30:00", policy=TimezonePolicy.NAMED, tz="Mars/Olympus")
    assert error.value.details["reason"] == "unknown_timezone"


def test_apply_timezone_policy_assumes_utc_by_default() -> None:
    naive = datetime(2024, 1, 15, 9, 30)
    assert apply_timezone_policy(naive, TimezonePolicy.ASSUME_UTC, None).tzinfo is UTC


def test_parse_timestamp_is_deterministic() -> None:
    first = _parse("15/01/2024 09:30:00")
    second = _parse("15/01/2024 09:30:00")
    assert first == second
