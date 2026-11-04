"""Value parsing: qualifiers, censoring, decimal conventions, finiteness.

The raw text is always preserved in the result. A censored value such as
``<0.01`` becomes a detection limit plus a qualifier; it is never converted to
zero. A non-finite or unparsable token becomes ``None`` with a coded reason, so
quality control can distinguish it from a missing value and from a real
measurement.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Final

from trendsmapp.domain.enums import ValueQualifier
from trendsmapp.ingestion.sniffing import DecimalStyle

__all__ = ["ValueParseResult", "parse_value"]

_QUALIFIER_PREFIXES: Final[tuple[tuple[str, ValueQualifier], ...]] = (
    ("<", ValueQualifier.BELOW_DETECTION_LIMIT),
    ("≤", ValueQualifier.BELOW_DETECTION_LIMIT),
    (">", ValueQualifier.ABOVE_DETECTION_LIMIT),
    ("≥", ValueQualifier.ABOVE_DETECTION_LIMIT),
    ("~", ValueQualifier.ESTIMATED),
)

_NOT_DETECTED = frozenset({"nd", "not detected", "not_detected", "n.d.", "<dl", "bdl"})
_NON_FINITE = frozenset(
    {"nan", "+nan", "-nan", "inf", "+inf", "-inf", "infinity", "+infinity", "-infinity"}
)

_THOUSANDS_POINT = re.compile(r"^\d{1,3}(,\d{3})+(\.\d+)?$")
_THOUSANDS_DOT_ONLY = re.compile(r"^\d{1,3}(\.\d{3})+$")
_THOUSANDS_DOT_AND_COMMA = re.compile(r"^\d{1,3}(\.\d{3})+(,\d+)?$")
_PLAIN_NUMBER = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")


@dataclass(frozen=True, slots=True)
class ValueParseResult:
    """The outcome of parsing one value cell."""

    raw: str
    value: float | None
    qualifier: ValueQualifier
    detection_limit: float | None
    reason: str | None

    @property
    def is_measurement(self) -> bool:
        """Return whether the cell carried a plain numeric measurement."""
        return self.value is not None and self.detection_limit is None


def parse_value(text: str, *, style: DecimalStyle = DecimalStyle.POINT) -> ValueParseResult:
    """Parse one value cell under the declared decimal convention."""
    raw = text.strip()
    if not raw:
        return ValueParseResult(
            raw=raw,
            value=None,
            qualifier=ValueQualifier.MEASURED,
            detection_limit=None,
            reason="missing_value",
        )

    lowered = raw.casefold()
    if lowered in _NOT_DETECTED:
        return ValueParseResult(
            raw=raw,
            value=None,
            qualifier=ValueQualifier.NOT_DETECTED,
            detection_limit=None,
            reason="not_detected",
        )

    qualifier = ValueQualifier.MEASURED
    body = raw
    for prefix, mapped in _QUALIFIER_PREFIXES:
        if raw.startswith(prefix):
            qualifier = mapped
            body = raw[len(prefix) :].strip()
            break

    number = _to_number(body, style)
    if isinstance(number, str):
        return ValueParseResult(
            raw=raw, value=None, qualifier=qualifier, detection_limit=None, reason=number
        )
    if not math.isfinite(number):
        return ValueParseResult(
            raw=raw, value=None, qualifier=qualifier, detection_limit=None, reason="non_finite"
        )
    if qualifier in {ValueQualifier.BELOW_DETECTION_LIMIT, ValueQualifier.ABOVE_DETECTION_LIMIT}:
        return ValueParseResult(
            raw=raw,
            value=None,
            qualifier=qualifier,
            detection_limit=number,
            reason=None,
        )
    return ValueParseResult(
        raw=raw, value=number, qualifier=qualifier, detection_limit=None, reason=None
    )


def _to_number(body: str, style: DecimalStyle) -> float | str:
    """Convert a token to a float under the decimal style, or return a reason."""
    token = body.strip()
    if not token:
        return "missing_value"
    if token.casefold() in _NON_FINITE:
        return "non_finite"
    if style is DecimalStyle.COMMA:
        if "," in token and "." in token:
            if not _THOUSANDS_DOT_AND_COMMA.fullmatch(token):
                return "ambiguous_decimal"
            token = token.replace(".", "").replace(",", ".")
        elif "," in token:
            token = token.replace(",", ".")
        elif "." in token:
            if not _THOUSANDS_DOT_ONLY.fullmatch(token):
                return "ambiguous_decimal"
            token = token.replace(".", "")
    elif "," in token:
        if not _THOUSANDS_POINT.fullmatch(token):
            return "ambiguous_decimal"
        token = token.replace(",", "")
    if not _PLAIN_NUMBER.fullmatch(token):
        return "invalid_number"
    try:
        return float(token)
    except ValueError:
        return "invalid_number"
