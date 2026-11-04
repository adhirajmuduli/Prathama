"""Tests for the versioned resource loader and the parameter registry."""

from __future__ import annotations

import pytest

from trendsmapp.errors import ValidationError
from trendsmapp.normalization.parameters import (
    ParameterRegistry,
    get_parameter_registry,
    normalize_alias,
)
from trendsmapp.resources import (
    SUPPORTED_RESOURCE_SCHEMA_VERSIONS,
    load_yaml_resource,
    read_resource_text,
)


def test_resource_loader_reads_the_shipped_documents() -> None:
    parameters = load_yaml_resource("parameters.v1.yaml")
    assert parameters["schema_version"] in SUPPORTED_RESOURCE_SCHEMA_VERSIONS
    assert isinstance(parameters["parameters"], list)
    assert parameters["parameters"]
    ranges = load_yaml_resource("qc_ranges.v1.yaml")
    assert ranges["schema_version"] in SUPPORTED_RESOURCE_SCHEMA_VERSIONS
    assert "plausibility_ranges" in ranges
    assert "detection_limits" in ranges


def test_resource_loader_rejects_path_traversal() -> None:
    for name in ["../pyproject.toml", "/etc/passwd", ".hidden", "sub/dir.yaml"]:
        with pytest.raises(ValidationError):
            read_resource_text(name)


def test_resource_loader_rejects_a_missing_resource() -> None:
    with pytest.raises(ValidationError):
        read_resource_text("does_not_exist.yaml")


def test_resource_loader_rejects_an_unsupported_schema_version() -> None:
    import trendsmapp.resources as resources

    original = resources.SUPPORTED_RESOURCE_SCHEMA_VERSIONS
    try:
        resources.SUPPORTED_RESOURCE_SCHEMA_VERSIONS = ("9.9.9",)
        with pytest.raises(ValidationError) as error:
            load_yaml_resource("parameters.v1.yaml")
        assert error.value.details["schema_version"] == "1.0.0"
    finally:
        resources.SUPPORTED_RESOURCE_SCHEMA_VERSIONS = original


def test_normalize_alias_collapses_case_and_punctuation() -> None:
    assert normalize_alias("  Dissolved-Oxygen ") == "dissolved_oxygen"
    assert normalize_alias("DO mg/L") == "do_mg_l"
    assert normalize_alias("pH") == "ph"


def test_parameter_registry_loads_and_validates() -> None:
    registry = get_parameter_registry()
    assert isinstance(registry, ParameterRegistry)
    assert len(registry.parameters) == 8
    by_id = {parameter.id: parameter for parameter in registry.parameters}
    oxygen = by_id["dissolved_oxygen"]
    assert oxygen.canonical_unit == "mg/L"
    assert oxygen.dimension == "[mass] / [length] ** 3"
    salinity = by_id["salinity"]
    assert salinity.canonical_unit == "1"
    assert salinity.dimension == "dimensionless"
    assert salinity.unit_aliases["psu"] == "1"


def test_parameter_registry_is_cached() -> None:
    assert get_parameter_registry() is get_parameter_registry()


@pytest.mark.parametrize(
    ("label", "expected_id", "via"),
    [
        ("dissolved_oxygen", "dissolved_oxygen", "id"),
        ("DO", "dissolved_oxygen", "alias"),
        ("Dissolved Oxygen", "dissolved_oxygen", "id"),
        ("salinity", "salinity", "id"),
        ("PSU", "salinity", "alias"),
        ("practical salinity", "salinity", "alias"),
        ("phosphat", "phosphat", "id"),
        ("PO4-P", "phosphat", "alias"),
        ("chl-a", "chlorophyll_a", "alias"),
        ("water temperature", "water_temperature", "id"),
        ("pH", "ph", "id"),
        ("something unknown", None, "none"),
        ("", None, "none"),
    ],
)
def test_parameter_resolution(label: str, expected_id: str | None, via: str) -> None:
    resolution = get_parameter_registry().resolve(label)
    if expected_id is None:
        assert resolution.parameter is None
        assert resolution.via == "none"
    else:
        assert resolution.parameter is not None
        assert resolution.parameter.id == expected_id
        assert resolution.via == via
        assert resolution.resolved is True


def test_parameter_registry_rejects_a_broken_resource(monkeypatch: pytest.MonkeyPatch) -> None:
    import trendsmapp.resources as resources

    def broken(name: str) -> dict[str, object]:
        return {
            "schema_version": "1.0.0",
            "parameters": [
                {
                    "id": "bad",
                    "label": "Bad",
                    "aliases": [],
                    "canonical_unit": "mg/L",
                    "dimension": "[length]",  # disagrees with mg/L
                    "unit_aliases": {},
                }
            ],
        }

    monkeypatch.setattr(resources, "load_yaml_resource", broken)
    with pytest.raises(ValidationError) as error:
        ParameterRegistry.load()
    assert "disagrees" in str(error.value)


def test_parameter_registry_rejects_duplicate_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    import trendsmapp.resources as resources

    def duplicated(name: str) -> dict[str, object]:
        entry = {
            "id": "dup",
            "label": "Dup",
            "aliases": [],
            "canonical_unit": "mg/L",
            "dimension": "[mass] / [length] ** 3",
            "unit_aliases": {},
        }
        return {"schema_version": "1.0.0", "parameters": [entry, dict(entry)]}

    monkeypatch.setattr(resources, "load_yaml_resource", duplicated)
    with pytest.raises(ValidationError) as error:
        ParameterRegistry.load()
    assert "twice" in str(error.value)


def test_parameter_registry_rejects_duplicate_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    import trendsmapp.resources as resources

    def conflicting(name: str) -> dict[str, object]:
        base = {
            "canonical_unit": "mg/L",
            "dimension": "[mass] / [length] ** 3",
            "unit_aliases": {},
        }
        return {
            "schema_version": "1.0.0",
            "parameters": [
                {"id": "a", "label": "A", "aliases": ["shared"], **base},
                {"id": "b", "label": "B", "aliases": ["Shared"], **base},
            ],
        }

    monkeypatch.setattr(resources, "load_yaml_resource", conflicting)
    with pytest.raises(ValidationError) as error:
        ParameterRegistry.load()
    assert "both" in str(error.value)
