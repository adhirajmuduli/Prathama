"""Negative-path tests: every validation and failure branch must be exercised.

These tests exist to prove that the registries and the canonicalizer fail
loudly and with coded reasons on bad input, rather than defaulting silently.
"""

from __future__ import annotations

import pytest

import trendsmapp.resources as resources_module
from trendsmapp.domain.enums import ColumnRole, DateOrder, LayoutKind, QcFlagCode, TimezonePolicy
from trendsmapp.errors import ValidationError
from trendsmapp.ingestion.chunking import TextBatch
from trendsmapp.ingestion.column_mapping import ColumnMapping, MappedColumn
from trendsmapp.ingestion.sniffing import DecimalStyle
from trendsmapp.ingestion.wide_to_long import LONG_SCHEMA_FIELDS
from trendsmapp.normalization import get_parameter_registry
from trendsmapp.normalization.canonicalize import NormalizedRow, canonicalize_row
from trendsmapp.normalization.coordinates import normalize_projected, normalize_wgs84
from trendsmapp.normalization.parameters import ParameterRegistry
from trendsmapp.normalization.timestamps import parse_timestamp
from trendsmapp.normalization.units import normalize_unit, normalize_value
from trendsmapp.normalization.values import parse_value

DATASET_ID = "ds_" + "a" * 32
DATASET_VERSION_ID = "dsv_" + "b" * 32


def _long_mapping() -> ColumnMapping:
    columns = [
        MappedColumn(column="station", role=ColumnRole.STATION),
        MappedColumn(column="latitude", role=ColumnRole.LATITUDE),
        MappedColumn(column="longitude", role=ColumnRole.LONGITUDE),
        MappedColumn(column="sampled_at", role=ColumnRole.TIMESTAMP),
        MappedColumn(column="parameter", role=ColumnRole.PARAMETER),
        MappedColumn(column="value", role=ColumnRole.VALUE),
        MappedColumn(column="unit", role=ColumnRole.UNIT),
    ]
    return ColumnMapping.model_validate(
        {"layout": LayoutKind.LONG, "columns": [c.model_dump() for c in columns]}
    )


def _row(values: tuple[str, ...], missing_fields: frozenset[str] = frozenset()) -> NormalizedRow:
    missing = tuple(name in missing_fields for name in LONG_SCHEMA_FIELDS)
    batch = TextBatch(
        columns=LONG_SCHEMA_FIELDS, rows=(values,), missing=(missing,), first_row_index=0
    )
    return next(NormalizedRow.from_batch(batch))


GOOD_ROW = (
    "St. A",
    "2024-01-15T09:30:00Z",
    "dissolved_oxygen",
    "6.8",
    "mg/L",
    "",
    "19.7350",
    "85.4700",
    "",
    "",
    "0.5",
    "",
    "2",
    "",
)


def _canonicalize(row: NormalizedRow, **overrides: object):
    kwargs: dict[str, object] = {
        "mapping": _long_mapping(),
        "dataset_id": DATASET_ID,
        "dataset_version_id": DATASET_VERSION_ID,
        "decimal_style": DecimalStyle.POINT,
    }
    kwargs.update(overrides)
    return canonicalize_row(row, **kwargs)  # type: ignore[arg-type]


# --- resource loader failure branches -----------------------------------------


def test_resource_loader_rejects_invalid_yaml(monkeypatch: pytest.MonkeyPatch) -> None:
    import yaml

    def broken_safe_load(text: str) -> object:
        raise yaml.YAMLError("bad yaml")

    monkeypatch.setattr(yaml, "safe_load", broken_safe_load)
    with pytest.raises(ValidationError) as error:
        resources_module.load_yaml_resource("parameters.v1.yaml")
    assert "not valid YAML" in str(error.value)


def test_resource_loader_rejects_a_non_mapping_document(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        resources_module, "read_resource_text", lambda name: "- just\n- a\n- list\n"
    )
    with pytest.raises(ValidationError) as error:
        resources_module.load_yaml_resource("anything.yaml")
    assert "mapping" in str(error.value)


def test_resource_loader_rejects_a_missing_schema_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(resources_module, "read_resource_text", lambda name: "parameters: []\n")
    with pytest.raises(ValidationError) as error:
        resources_module.load_yaml_resource("anything.yaml")
    assert "schema_version" in str(error.value)


def test_resource_loader_rejects_a_non_string_schema_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        resources_module, "read_resource_text", lambda name: "schema_version: 1.0\n"
    )
    with pytest.raises(ValidationError) as error:
        resources_module.load_yaml_resource("anything.yaml")
    assert "schema_version" in str(error.value)


def test_resource_loader_rejects_a_package_lookup_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib.resources

    def broken_files(package: str) -> object:
        raise FileNotFoundError(package)

    monkeypatch.setattr(importlib.resources, "files", broken_files)
    with pytest.raises(ValidationError) as error:
        resources_module.read_resource_text("parameters.v1.yaml")
    assert "not shipped" in str(error.value)


# --- parameter registry validation branches -----------------------------------


def _registry_with(
    monkeypatch: pytest.MonkeyPatch, parameters: list[dict[str, object]]
) -> ParameterRegistry:
    monkeypatch.setattr(
        resources_module,
        "load_yaml_resource",
        lambda name: {"schema_version": "1.0.0", "parameters": parameters},
    )
    return ParameterRegistry.load()


def _valid_entry(**overrides: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "id": "test_param",
        "label": "Test param",
        "aliases": [],
        "canonical_unit": "mg/L",
        "dimension": "[mass] / [length] ** 3",
        "unit_aliases": {},
    }
    entry.update(overrides)
    return entry


@pytest.mark.parametrize(
    ("entry", "needle"),
    [
        ("not-a-dict", "mapping"),
        (_valid_entry(id="Bad Id"), "id"),
        (_valid_entry(id=""), "id"),
        (_valid_entry(label=""), "label"),
        (_valid_entry(label=42), "label"),
        (_valid_entry(canonical_unit=""), "canonical unit"),
        (_valid_entry(canonical_unit="not a unit"), "not a known unit"),
        (_valid_entry(dimension=""), "dimension"),
        (_valid_entry(dimension="[length]"), "disagrees"),
        (_valid_entry(aliases="nope"), "list of strings"),
        (_valid_entry(aliases=[1]), "list of strings"),
        (_valid_entry(unit_aliases=["not", "a", "map"]), "mapping"),
        (_valid_entry(unit_aliases={"psu": 1}), "strings to strings"),
        (_valid_entry(unit_aliases={"psu": "not a unit"}), "not a known unit"),
        (_valid_entry(unit_aliases={"m": "m"}), "disagrees"),
    ],
)
def test_parameter_registry_rejects_broken_entries(
    monkeypatch: pytest.MonkeyPatch, entry: object, needle: str
) -> None:
    with pytest.raises(ValidationError) as error:
        _registry_with(monkeypatch, [entry])  # type: ignore[arg-type]
    assert needle in str(error.value)


def test_parameter_registry_rejects_a_non_list_parameters_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        resources_module,
        "load_yaml_resource",
        lambda name: {"schema_version": "1.0.0", "parameters": "nope"},
    )
    with pytest.raises(ValidationError) as error:
        ParameterRegistry.load()
    assert "parameters" in str(error.value)


def test_parameter_registry_rejects_an_empty_parameter_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValidationError):
        _registry_with(monkeypatch, [])


def test_parameter_registry_accepts_a_non_string_display_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _registry_with(monkeypatch, [_valid_entry(display_name=42)])
    assert registry.parameters[0].display_name is None


# --- canonicalize failure branches ---------------------------------------------


def test_canonicalize_reports_a_unit_when_the_parameter_is_unknown() -> None:
    row = _row(
        (
            "St. A",
            "2024-01-15T09:30:00Z",
            "mystery",
            "5",
            "widgets",
            "",
            "19.7",
            "85.4",
            "",
            "",
            "",
            "",
            "2",
            "",
        )
    )
    result = _canonicalize(row)
    assert result.observation is not None
    assert any(issue.code == QcFlagCode.UNKNOWN_PARAMETER.value for issue in result.issues)
    assert any(issue.code == QcFlagCode.UNKNOWN_UNIT.value for issue in result.issues)


def test_canonicalize_flags_an_invalid_value_text() -> None:
    row = _row(
        (
            "St. A",
            "2024-01-15T09:30:00Z",
            "dissolved_oxygen",
            "not a number",
            "mg/L",
            "",
            "19.7",
            "85.4",
            "",
            "",
            "",
            "",
            "2",
            "",
        )
    )
    result = _canonicalize(row)
    assert result.observation is not None
    assert result.observation.canonical_value is None
    assert any("could not be parsed" in issue.message for issue in result.issues)


def test_canonicalize_skips_rows_with_out_of_range_coordinates() -> None:
    row = _row(
        (
            "St. A",
            "2024-01-15T09:30:00Z",
            "dissolved_oxygen",
            "6.8",
            "mg/L",
            "",
            "95",
            "85.4",
            "",
            "",
            "",
            "",
            "2",
            "",
        )
    )
    result = _canonicalize(row)
    assert result.observation is None
    assert result.skipped is not None
    assert result.skipped.reason == QcFlagCode.COORDINATE_OUT_OF_RANGE.value


def test_canonicalize_flags_an_invalid_depth() -> None:
    row = _row(
        (
            "St. A",
            "2024-01-15T09:30:00Z",
            "dissolved_oxygen",
            "6.8",
            "mg/L",
            "",
            "19.7",
            "85.4",
            "",
            "",
            "deep",
            "",
            "2",
            "",
        )
    )
    result = _canonicalize(row)
    assert result.observation is not None
    assert result.observation.sampling_depth_m is None
    assert any(issue.code == "invalid_depth" for issue in result.issues)


def test_canonicalize_requires_a_source_crs_for_projected_input() -> None:
    mapping = ColumnMapping.model_validate(
        {
            "layout": LayoutKind.LONG,
            "columns": [
                {"column": "station", "role": "station"},
                {"column": "easting", "role": "easting"},
                {"column": "northing", "role": "northing"},
                {"column": "sampled_at", "role": "timestamp"},
                {"column": "parameter", "role": "parameter"},
                {"column": "value", "role": "value"},
                {"column": "unit", "role": "unit"},
            ],
        }
    )
    row = _row(
        (
            "St. A",
            "2024-01-15T09:30:00Z",
            "dissolved_oxygen",
            "6.8",
            "mg/L",
            "",
            "",
            "",
            "646000",
            "2185000",
            "",
            "",
            "2",
            "",
        ),
        missing_fields=frozenset({"latitude", "longitude"}),
    )
    result = _canonicalize(row, mapping=mapping)
    assert result.observation is None
    assert result.skipped is not None
    assert result.skipped.reason == "missing_coordinate"


# --- coordinates failure branches ----------------------------------------------


def test_normalize_wgs84_flags_an_out_of_range_longitude() -> None:
    result = normalize_wgs84("19.7", "200")
    assert result.longitude is None
    assert any("out_of_range" in issue for issue in result.issues)


def test_normalize_projected_records_a_projection_failure() -> None:
    result = normalize_projected("1e308", "1e308", source_crs="EPSG:32644")
    assert result.latitude is None or any("projection" in issue for issue in result.issues)


# --- timestamp failure branches -------------------------------------------------


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("2024-01-15T25:00:00", None),
        ("15/01/2024 25:00", "invalid_time"),
        ("2024-13-01", None),
        ("00/01/2024", "invalid_date"),
        ("2024-00-10", None),
    ],
)
def test_parse_timestamp_rejects_invalid_calendar_and_time_values(
    text: str, reason: str | None
) -> None:
    with pytest.raises(ValidationError):
        parse_timestamp(
            text, date_order=DateOrder.DAY_FIRST, timezone_policy=TimezonePolicy.ASSUME_UTC
        )


# --- unit failure branches -------------------------------------------------------


def test_normalize_value_records_a_conversion_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from trendsmapp.domain.units import UnitRegistry, get_unit_registry
    from trendsmapp.errors import ValidationError as TrendsmappValidationError

    registry = get_unit_registry()
    assert isinstance(registry, UnitRegistry)

    def failing_convert(self: UnitRegistry, value: float, from_unit: str, to_unit: str):  # type: ignore[no-untyped-def]
        raise TrendsmappValidationError(
            "conversion refused", details={"from_unit": from_unit, "to_unit": to_unit}
        )

    monkeypatch.setattr(registry, "convert", failing_convert.__get__(registry))
    oxygen = get_parameter_registry().resolve("DO").parameter
    assert oxygen is not None
    unit = normalize_unit("mg/L", parameter=oxygen, unit_registry=registry)
    normalized = normalize_value(parse_value("6.8"), unit, parameter=oxygen, unit_registry=registry)
    assert normalized.canonical_value is None
    assert any("conversion_failed" in issue for issue in normalized.issues)


def test_normalize_unit_reports_a_missing_unit() -> None:
    oxygen = get_parameter_registry().resolve("DO").parameter
    assert oxygen is not None
    assert normalize_unit("", parameter=oxygen).issue == "missing_unit"


# --- value failure branches -------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "style", "reason"),
    [
        ("1.2.3", DecimalStyle.POINT, "invalid_number"),
        ("12..5", DecimalStyle.POINT, "invalid_number"),
        ("", DecimalStyle.COMMA, "missing_value"),
        ("1.2.3", DecimalStyle.COMMA, "ambiguous_decimal"),
        ("1,2,3", DecimalStyle.COMMA, "invalid_number"),
    ],
)
def test_parse_value_covers_the_remaining_decimal_failures(
    text: str, style: DecimalStyle, reason: str
) -> None:
    assert parse_value(text, style=style).reason == reason
