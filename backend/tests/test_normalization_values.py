"""Tests for value parsing: qualifiers, censoring, decimals, finiteness."""

from __future__ import annotations

import pytest

from trendsmapp.domain.enums import ValueQualifier
from trendsmapp.ingestion.sniffing import DecimalStyle
from trendsmapp.normalization.values import parse_value

POINT = DecimalStyle.POINT
COMMA = DecimalStyle.COMMA


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("6.8", 6.8),
        ("-3.5", -3.5),
        ("+12", 12.0),
        ("0", 0.0),
        ("1.5e3", 1500.0),
        ("2E-2", 0.02),
        (".5", 0.5),
        ("1,234.5", 1234.5),
        ("1,234,567", 1234567.0),
    ],
)
def test_parse_value_reads_plain_numbers_under_point_style(text: str, value: float) -> None:
    result = parse_value(text, style=POINT)
    assert result.value == pytest.approx(value)
    assert result.qualifier is ValueQualifier.MEASURED
    assert result.detection_limit is None
    assert result.reason is None
    assert result.raw == text
    assert result.is_measurement


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("12,4", 12.4),
        ("1.234,5", 1234.5),
        ("1.234.567,89", 1234567.89),
        ("0,5", 0.5),
    ],
)
def test_parse_value_reads_comma_decimal_numbers(text: str, value: float) -> None:
    result = parse_value(text, style=COMMA)
    assert result.value == pytest.approx(value)
    assert result.reason is None


def test_parse_value_reads_a_dot_thousands_number_under_comma_style() -> None:
    assert parse_value("1.234", style=COMMA).value == pytest.approx(1234.0)


@pytest.mark.parametrize(
    ("text", "qualifier", "limit"),
    [
        ("<0.01", ValueQualifier.BELOW_DETECTION_LIMIT, 0.01),
        ("≤0.05", ValueQualifier.BELOW_DETECTION_LIMIT, 0.05),
        (">25", ValueQualifier.ABOVE_DETECTION_LIMIT, 25.0),
        ("≥100", ValueQualifier.ABOVE_DETECTION_LIMIT, 100.0),
    ],
)
def test_parse_value_keeps_censored_values_as_limits(
    text: str, qualifier: ValueQualifier, limit: float
) -> None:
    result = parse_value(text, style=POINT)
    assert result.value is None
    assert result.qualifier is qualifier
    assert result.detection_limit == pytest.approx(limit)
    assert result.reason is None
    assert not result.is_measurement


def test_parse_value_never_turns_a_censored_value_into_zero() -> None:
    result = parse_value("<0.01", style=POINT)
    assert result.value is None
    assert result.detection_limit == pytest.approx(0.01)


@pytest.mark.parametrize("text", ["ND", "nd", "not detected", "N.D.", "<DL", "BDL"])
def test_parse_value_recognizes_not_detected(text: str) -> None:
    result = parse_value(text, style=POINT)
    assert result.value is None
    assert result.qualifier is ValueQualifier.NOT_DETECTED
    assert result.reason == "not_detected"


def test_parse_value_marks_estimated_values() -> None:
    result = parse_value("~3.2", style=POINT)
    assert result.value == pytest.approx(3.2)
    assert result.qualifier is ValueQualifier.ESTIMATED


@pytest.mark.parametrize(
    ("text", "style", "reason"),
    [
        ("", POINT, "missing_value"),
        ("   ", POINT, "missing_value"),
        ("nan", POINT, "non_finite"),
        ("inf", POINT, "non_finite"),
        ("-Infinity", POINT, "non_finite"),
        ("1e999", POINT, "non_finite"),
        ("abc", POINT, "invalid_number"),
        ("12 mg", POINT, "invalid_number"),
        ("12%", POINT, "invalid_number"),
        ("1,5", POINT, "ambiguous_decimal"),
        ("1.23", COMMA, "ambiguous_decimal"),
        ("1,23,4", POINT, "ambiguous_decimal"),
        ("--3", POINT, "invalid_number"),
        ("1 234", POINT, "invalid_number"),
    ],
)
def test_parse_value_reports_coded_reasons(text: str, style: DecimalStyle, reason: str) -> None:
    result = parse_value(text, style=style)
    assert result.value is None
    assert result.reason == reason
    assert result.raw == text.strip()


def test_parse_value_preserves_the_raw_text() -> None:
    for text in ["<0.01", "1,234.5", "nan", "  6.8  "]:
        assert parse_value(text, style=POINT).raw == text.strip()


def test_parse_value_is_deterministic() -> None:
    assert parse_value("12,4", style=COMMA) == parse_value("12,4", style=COMMA)
