"""Tests for unit normalization and dimension-checked conversion."""

from __future__ import annotations

import pytest

from trendsmapp.ingestion.sniffing import DecimalStyle
from trendsmapp.normalization.parameters import get_parameter_registry
from trendsmapp.normalization.units import normalize_unit, normalize_value
from trendsmapp.normalization.values import parse_value


def _oxygen() -> object:
    return get_parameter_registry().resolve("DO").parameter


def _salinity() -> object:
    return get_parameter_registry().resolve("salinity").parameter


def test_unit_alias_resolves_a_spelling_pint_cannot_parse() -> None:
    result = normalize_unit("psu", parameter=_salinity())
    assert result.unit_expression == "1"
    assert result.issue is None
    assert result.resolved


def test_exact_unit_resolves_through_the_registry() -> None:
    result = normalize_unit("mg/L", parameter=_oxygen())
    assert result.unit_expression == "mg/L"
    assert result.canonical_unit_name == "milligram / liter"
    assert result.case_corrected is False


def test_casefold_retry_is_accepted_only_with_a_matching_dimension() -> None:
    result = normalize_unit("MG/L", parameter=_oxygen())
    assert result.case_corrected is True
    assert result.issue is None
    assert result.unit_expression == "mg/l"


def test_a_dimension_mismatch_is_reported_not_guessed() -> None:
    result = normalize_unit("m/s", parameter=_oxygen())
    assert result.issue == "incompatible_unit"
    assert not result.resolved


def test_an_unknown_unit_is_reported() -> None:
    result = normalize_unit("widgets", parameter=_oxygen())
    assert result.issue == "unknown_unit"
    assert result.unit_expression is None


def test_a_real_but_wrong_dimension_unit_is_incompatible() -> None:
    result = normalize_unit("furlongs per fortnight", parameter=_oxygen())
    assert result.issue == "incompatible_unit"


def test_a_missing_unit_is_reported() -> None:
    assert normalize_unit("  ", parameter=_oxygen()).issue == "missing_unit"


def test_conversion_is_dimension_checked_and_records_the_factor() -> None:
    value = normalize_value(
        parse_value("6800", style=DecimalStyle.POINT),
        normalize_unit("ug/L", parameter=_oxygen()),
        parameter=_oxygen(),
    )
    assert value.canonical_value == pytest.approx(6.8)
    assert value.canonical_unit == "mg/L"
    assert value.conversion is not None
    assert value.conversion.factor == pytest.approx(0.001)
    assert value.conversion.dimension == "[mass] / [length] ** 3"
    assert value.issues == ()


def test_detection_limits_are_converted_with_the_same_factor() -> None:
    value = normalize_value(
        parse_value("<10", style=DecimalStyle.POINT),
        normalize_unit("ug/L", parameter=_oxygen()),
        parameter=_oxygen(),
    )
    assert value.canonical_value is None
    assert value.detection_limit == pytest.approx(0.01)
    assert value.canonical_unit == "mg/L"


def test_dimensionless_units_pass_through() -> None:
    value = normalize_value(
        parse_value("12.4", style=DecimalStyle.POINT),
        normalize_unit("psu", parameter=_salinity()),
        parameter=_salinity(),
    )
    assert value.canonical_value == pytest.approx(12.4)
    assert value.canonical_unit == "1"


def test_incompatible_units_leave_the_value_uncanonicalized() -> None:
    value = normalize_value(
        parse_value("3", style=DecimalStyle.POINT),
        normalize_unit("m/s", parameter=_oxygen()),
        parameter=_oxygen(),
    )
    assert value.canonical_value is None
    assert value.canonical_unit is None
    assert "incompatible_unit" in value.issues


def test_case_correction_is_recorded_as_an_issue() -> None:
    value = normalize_value(
        parse_value("6.8", style=DecimalStyle.POINT),
        normalize_unit("MG/L", parameter=_oxygen()),
        parameter=_oxygen(),
    )
    assert value.canonical_value == pytest.approx(6.8)
    assert any("case corrected" in issue for issue in value.issues)


def test_temperature_converts_between_scales() -> None:
    temperature = get_parameter_registry().resolve("water temperature").parameter
    value = normalize_value(
        parse_value("86", style=DecimalStyle.POINT),
        normalize_unit("degF", parameter=temperature),
        parameter=temperature,
    )
    assert value.canonical_value == pytest.approx(30.0)
    assert value.canonical_unit == "degC"
