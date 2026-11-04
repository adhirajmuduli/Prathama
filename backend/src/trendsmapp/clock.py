"""UTC clock abstraction used to keep time logic out of the domain code.

Every timestamp produced by the application comes from a :class:`Clock`. Tests
substitute :class:`FrozenClock` so that manifests, expiry checks, and run
metadata are deterministic.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable

__all__ = ["Clock", "FrozenClock", "SystemClock", "ensure_utc", "isoformat_z", "utc_now"]


@runtime_checkable
class Clock(Protocol):
    """A source of the current UTC time."""

    def now(self) -> datetime:
        """Return the current time as a timezone-aware UTC datetime."""
        ...


class SystemClock:
    """The default clock, reading the host clock in UTC."""

    __slots__ = ()

    def now(self) -> datetime:
        """Return the current time as a timezone-aware UTC datetime."""
        return datetime.now(UTC)


class FrozenClock:
    """A deterministic clock for tests and reproducible replays."""

    __slots__ = ("_current",)

    def __init__(self, current: datetime) -> None:
        self._current = ensure_utc(current)

    def now(self) -> datetime:
        """Return the frozen time."""
        return self._current

    def advance(self, delta: timedelta) -> None:
        """Move the frozen time forward by ``delta``."""
        self._current = self._current + delta

    def set(self, current: datetime) -> None:
        """Set the frozen time to ``current``."""
        self._current = ensure_utc(current)


def utc_now() -> datetime:
    """Return the current UTC time from the system clock."""
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """Return ``value`` as a timezone-aware UTC datetime.

    Naive datetimes are rejected: interpreting a naive timestamp as UTC would
    silently invent an offset.
    """
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("A timezone-aware datetime is required.")
    return value.astimezone(UTC)


def isoformat_z(value: datetime) -> str:
    """Serialize a datetime as an RFC 3339 UTC timestamp with a ``Z`` suffix."""
    return ensure_utc(value).isoformat().replace("+00:00", "Z")
