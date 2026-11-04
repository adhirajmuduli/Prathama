"""Timestamp normalization under a declared date order and timezone policy.

A timestamp is never guessed. The column mapping declares the date order and
the timezone policy; this module applies exactly those declarations and fails
with a coded reason when a value cannot be read under them. Partial dates
(``2024`` or ``2024-01``), two-digit years, and bare Excel serial numbers are
rejected rather than interpreted, because each of them has more than one
meaning and the policy cannot be applied to a value with no day.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from trendsmapp.domain.enums import DateOrder, TimezonePolicy
from trendsmapp.errors import ValidationError

__all__ = [
    "apply_timezone_policy",
    "parse_timestamp",
]

_MONTHS: dict[str, int] = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

_PARTIAL_DATE = re.compile(r"^\d{4}(-\d{2})?$")
_NUMERIC_ONLY = re.compile(r"^[+-]?\d+(\.\d+)?([eE][+-]?\d+)?$")
_NUMERIC_DATE = re.compile(
    r"^(\d{1,4})([-/.])(\d{1,4})\2(\d{1,4})(?:[T ](\d{1,2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?)?$"
)
_DAY_MONTH_NAME_YEAR = re.compile(r"^(\d{1,2})[- ]([A-Za-z]{3,9})[- ,]+(\d{4})$")
_MONTH_NAME_DAY_YEAR = re.compile(r"^([A-Za-z]{3,9})[- ]+(\d{1,2}),?[- ]+(\d{4})$")
_YEAR_MONTH_NAME_DAY = re.compile(r"^(\d{4})[- ]([A-Za-z]{3,9})[- ](\d{1,2})$")


def parse_timestamp(
    text: str,
    *,
    date_order: DateOrder,
    timezone_policy: TimezonePolicy,
    timezone_name: str | None = None,
) -> datetime:
    """Parse one timestamp into an aware UTC datetime.

    The declared ``date_order`` resolves day/month ambiguity in numeric dates;
    a value that is impossible under the declared order is an error, never a
    silent swap. ISO 8601 input is unambiguous and unaffected by ``date_order``.
    """
    raw = text.strip()
    if not raw:
        raise ValidationError("A timestamp value is empty.", details={"reason": "empty_timestamp"})
    if _PARTIAL_DATE.fullmatch(raw):
        raise ValidationError(
            f"'{raw}' is a partial date; an observation needs a full date or datetime.",
            details={"reason": "partial_date", "value": raw},
        )
    if _NUMERIC_ONLY.fullmatch(raw):
        raise ValidationError(
            "A bare number is not a timestamp; spreadsheet serial dates are not interpreted.",
            details={"reason": "numeric_timestamp", "value": raw},
        )

    parsed = _try_iso(raw)
    if parsed is not None:
        return apply_timezone_policy(parsed, timezone_policy, timezone_name)

    parsed = _try_month_name(raw)
    if parsed is not None:
        return apply_timezone_policy(parsed, timezone_policy, timezone_name)

    parsed = _try_numeric_date(raw, date_order)
    if parsed is not None:
        return apply_timezone_policy(parsed, timezone_policy, timezone_name)

    raise ValidationError(
        f"'{raw}' could not be parsed as a timestamp under the declared date "
        f"order '{date_order.value}'.",
        details={"reason": "unparsable_timestamp", "value": raw},
    )


def apply_timezone_policy(
    value: datetime,
    policy: TimezonePolicy,
    timezone_name: str | None,
) -> datetime:
    """Attach or require an offset, then return the instant in UTC."""
    if value.tzinfo is not None:
        return value.astimezone(UTC)
    if policy is TimezonePolicy.ASSUME_UTC:
        return value.replace(tzinfo=UTC)
    if policy is TimezonePolicy.REQUIRE_OFFSET:
        raise ValidationError(
            "The timestamp has no offset and the declared policy requires one.",
            details={"reason": "missing_offset"},
        )
    if policy is TimezonePolicy.NAMED:
        if not timezone_name:
            raise ValidationError(
                "The named timezone policy requires a timezone name.",
                details={"reason": "missing_timezone_name"},
            )
        try:
            zone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise ValidationError(
                f"The timezone '{timezone_name}' is not known to this system.",
                details={"reason": "unknown_timezone", "timezone": timezone_name},
            ) from exc
        return value.replace(tzinfo=zone).astimezone(UTC)
    raise ValidationError(
        f"Unknown timezone policy '{policy.value}'.",
        details={"reason": "unknown_timezone_policy"},
    )


def _try_iso(raw: str) -> datetime | None:
    """Try ISO 8601, which Python parses directly and unambiguously."""
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _try_month_name(raw: str) -> datetime | None:
    """Try month-name forms, using a locale-independent month table."""
    for pattern, layout in (
        (_DAY_MONTH_NAME_YEAR, "dmy"),
        (_MONTH_NAME_DAY_YEAR, "mdy"),
        (_YEAR_MONTH_NAME_DAY, "ymd"),
    ):
        match = pattern.fullmatch(raw)
        if match is None:
            continue
        groups = match.groups()
        month_token = next((g for g in groups if g.isalpha()), None)
        if month_token is None:
            continue
        month = _MONTHS.get(month_token[:3].casefold())
        if month is None:
            continue
        numbers = [int(g) for g in groups if g.isdigit()]
        if len(numbers) != 2:
            continue
        if layout == "dmy" or layout == "mdy":
            day, year = numbers
        else:
            year, day = numbers
        return _build_date(year, month, day, raw, reason="invalid_date")
    return None


def _try_numeric_date(raw: str, date_order: DateOrder) -> datetime | None:
    """Parse a numeric date under the declared order, with an optional time.

    The year is the component that is at least 1000, or the one above 31 when
    no component reaches 1000. A two-digit year is rejected, because the
    century cannot be assumed. The remaining two components are assigned by
    the declared order; a value that is impossible under that order is an
    error, never a silent swap.
    """
    match = _NUMERIC_DATE.fullmatch(raw)
    if match is None:
        return None
    first = int(match.group(1))
    second = int(match.group(3))
    fourth = int(match.group(4))
    hour = int(match.group(5)) if match.group(5) else None
    minute = int(match.group(6)) if match.group(6) else 0
    second_of_minute = int(match.group(7)) if match.group(7) else 0
    microsecond = int((match.group(8) or "0").ljust(6, "0")[:6]) if match.group(8) else 0

    if first >= 1000:
        year, a, b = first, second, fourth
        month, day = a, b  # year-first numeric form: yyyy/mm/dd
        year_first = True
    elif second >= 1000:
        year, a, b = second, first, fourth
        year_first = False
    elif fourth >= 1000:
        year, a, b = fourth, first, second
        year_first = False
    elif first > 31:
        year, a, b = first, second, fourth
        year_first = False
    elif fourth > 31:
        year, a, b = fourth, first, second
        year_first = False
    else:
        raise ValidationError(
            f"'{raw}' has no four-digit year and a two-digit year cannot be assumed.",
            details={"reason": "ambiguous_year", "value": raw},
        )

    if not year_first:
        if date_order is DateOrder.DAY_FIRST:
            day, month = a, b
        else:
            month, day = a, b

    dt = _build_date(year, month, day, raw, reason="invalid_date")
    if hour is not None:
        try:
            dt = dt.replace(
                hour=hour, minute=minute, second=second_of_minute, microsecond=microsecond
            )
        except ValueError as exc:
            raise ValidationError(
                f"'{raw}' has an invalid time component.",
                details={"reason": "invalid_time", "value": raw},
            ) from exc
    return dt


def _build_date(year: int, month: int, day: int, raw: str, *, reason: str) -> datetime:
    """Build a naive datetime, translating calendar errors."""
    try:
        return datetime(year, month, day)
    except ValueError as exc:
        raise ValidationError(
            f"'{raw}' is not a real calendar date under the declared date order.",
            details={"reason": reason, "value": raw},
        ) from exc
