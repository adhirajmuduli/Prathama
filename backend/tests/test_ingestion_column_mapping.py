"""Tests for the versioned column mapping, validation, and role resolution."""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from trendsmapp.domain.enums import (
    ColumnRole,
    DateOrder,
    DuplicatePolicy,
    LayoutKind,
    TimezonePolicy,
)
from trendsmapp.errors import ValidationError
from trendsmapp.ingestion.column_mapping import (
    MAPPING_SCHEMA_VERSION,
    ColumnMapping,
    MappedColumn,
    propose_mapping,
    resolve_mapping,
    validate_mapping,
)

LONG_FIELDS = (
    "station",
    "latitude",
    "longitude",
    "sampled_at",
    "parameter",
    "value",
    "unit",
    "qualifier",
    "depth_m",
    "notes",
)


def long_mapping(**overrides: object) -> ColumnMapping:
    """Return a valid long mapping for the canonical fixture fields."""
    columns = [
        MappedColumn(column="station", role=ColumnRole.STATION),
        MappedColumn(column="latitude", role=ColumnRole.LATITUDE),
        MappedColumn(column="longitude", role=ColumnRole.LONGITUDE),
        MappedColumn(column="sampled_at", role=ColumnRole.TIMESTAMP),
        MappedColumn(column="parameter", role=ColumnRole.PARAMETER),
        MappedColumn(column="value", role=ColumnRole.VALUE),
        MappedColumn(column="unit", role=ColumnRole.UNIT),
        MappedColumn(column="qualifier", role=ColumnRole.QUALIFIER),
        MappedColumn(column="depth_m", role=ColumnRole.DEPTH),
        MappedColumn(column="notes", role=ColumnRole.IGNORED),
    ]
    data: dict[str, object] = {"layout": LayoutKind.LONG, "columns": columns}
    data.update(overrides)
    return ColumnMapping.model_validate(data)


def test_column_mapping_defaults_are_explicit_and_versioned() -> None:
    mapping = long_mapping()
    assert mapping.schema_version == MAPPING_SCHEMA_VERSION
    assert mapping.date_order is DateOrder.DAY_FIRST
    assert mapping.timezone_policy is TimezonePolicy.ASSUME_UTC
    assert mapping.duplicate_policy is DuplicatePolicy.FLAG_ALL
    assert mapping.default_parameter is None
    assert mapping.default_unit is None


def test_column_mapping_rejects_unknown_fields() -> None:
    with pytest.raises(PydanticValidationError):
        long_mapping(unexpected="nope")


def test_column_mapping_requires_a_confirmable_layout() -> None:
    with pytest.raises(PydanticValidationError) as error:
        long_mapping(layout=LayoutKind.UNKNOWN)
    assert "confirm a layout" in str(error.value)


def test_column_mapping_requires_a_wide_axis() -> None:
    with pytest.raises(PydanticValidationError) as error:
        long_mapping(layout=LayoutKind.WIDE)
    assert "axis" in str(error.value)


def test_column_mapping_rejects_a_wide_axis_on_a_long_layout() -> None:
    with pytest.raises(PydanticValidationError):
        long_mapping(wide_axis="stations")


def test_column_mapping_pairs_the_named_timezone_policy() -> None:
    with pytest.raises(PydanticValidationError):
        long_mapping(timezone_policy=TimezonePolicy.NAMED)
    with pytest.raises(PydanticValidationError):
        long_mapping(timezone_name="Asia/Kolkata")
    named = long_mapping(timezone_policy=TimezonePolicy.NAMED, timezone_name="Asia/Kolkata")
    assert named.timezone_name == "Asia/Kolkata"


def test_validate_mapping_accepts_a_complete_long_mapping() -> None:
    validation = validate_mapping(
        long_mapping(),
        fields=LONG_FIELDS,
        numeric_fields=frozenset({"latitude", "longitude", "value"}),
        date_fields=frozenset({"sampled_at"}),
    )
    assert validation.warnings == ()


def test_validate_mapping_rejects_unknown_columns() -> None:
    columns = list(long_mapping().columns)[:-1]
    columns.append(MappedColumn(column="missing_column", role=ColumnRole.IGNORED))
    mapping = ColumnMapping.model_validate(
        {"layout": LayoutKind.LONG, "columns": [item.model_dump() for item in columns]}
    )
    with pytest.raises(ValidationError) as error:
        validate_mapping(mapping, fields=LONG_FIELDS)
    assert error.value.details["column"] == "missing_column"


def test_validate_mapping_rejects_duplicate_column_names() -> None:
    columns = list(long_mapping().columns)
    columns.append(MappedColumn(column="station", role=ColumnRole.IGNORED))
    mapping = ColumnMapping.model_validate(
        {"layout": LayoutKind.LONG, "columns": [item.model_dump() for item in columns]}
    )
    with pytest.raises(ValidationError) as error:
        validate_mapping(mapping, fields=LONG_FIELDS)
    assert "more than once" in str(error.value)


def test_validate_mapping_reports_unassigned_columns_as_warnings() -> None:
    columns = [item for item in long_mapping().columns if item.column != "notes"]
    mapping = ColumnMapping.model_validate(
        {"layout": LayoutKind.LONG, "columns": [item.model_dump() for item in columns]}
    )
    validation = validate_mapping(mapping, fields=LONG_FIELDS)
    assert any("notes" in warning for warning in validation.warnings)


def _assert_structural_error(error: pytest.ExceptionInfo, *needles: str) -> None:
    """Assert that a validation failure lists every expected reason."""
    errors = error.value.details.get("errors", [])
    for needle in needles:
        assert any(needle in item for item in errors), (needle, errors)


def test_validate_mapping_enforces_long_structure() -> None:
    all_columns = list(long_mapping().columns)
    filtered_sets = [
        [item for item in all_columns if item.role is not ColumnRole.TIMESTAMP],
        [item for item in all_columns if item.role is not ColumnRole.VALUE],
        [
            item
            for item in all_columns
            if item.role not in {ColumnRole.STATION, ColumnRole.LATITUDE, ColumnRole.LONGITUDE}
        ],
    ]
    for filtered in filtered_sets:
        mapping = ColumnMapping.model_validate(
            {"layout": LayoutKind.LONG, "columns": [item.model_dump() for item in filtered]}
        )
        with pytest.raises(ValidationError) as error:
            validate_mapping(mapping, fields=LONG_FIELDS)
        assert error.value.details["errors"], "expected at least one structural error"


def test_validate_mapping_accepts_a_default_parameter_without_a_column() -> None:
    columns = [item for item in long_mapping().columns if item.role is not ColumnRole.PARAMETER]
    mapping = ColumnMapping.model_validate(
        {
            "layout": LayoutKind.LONG,
            "columns": [item.model_dump() for item in columns],
            "default_parameter": "dissolved_oxygen",
        }
    )
    validation = validate_mapping(
        mapping,
        fields=LONG_FIELDS,
        numeric_fields=frozenset({"latitude", "longitude", "value"}),
    )
    assert validation.warnings
    assert all("without a role" in warning for warning in validation.warnings)


def test_validate_mapping_requires_a_parameter_source() -> None:
    columns = [item for item in long_mapping().columns if item.role is not ColumnRole.PARAMETER]
    mapping = ColumnMapping.model_validate(
        {"layout": LayoutKind.LONG, "columns": [item.model_dump() for item in columns]}
    )
    with pytest.raises(ValidationError) as error:
        validate_mapping(
            mapping,
            fields=LONG_FIELDS,
            numeric_fields=frozenset({"latitude", "longitude", "value"}),
        )
    _assert_structural_error(error, "parameter")


def test_validate_mapping_requires_a_unit_source() -> None:
    columns = [item for item in long_mapping().columns if item.role is not ColumnRole.UNIT]
    mapping = ColumnMapping.model_validate(
        {"layout": LayoutKind.LONG, "columns": [item.model_dump() for item in columns]}
    )
    with pytest.raises(ValidationError) as error:
        validate_mapping(
            mapping,
            fields=LONG_FIELDS,
            numeric_fields=frozenset({"latitude", "longitude", "value"}),
        )
    _assert_structural_error(error, "unit")


def test_validate_mapping_accepts_projected_coordinates_with_a_crs() -> None:
    fields = ("station", "easting", "northing", "sampled_at", "parameter", "value", "unit")
    columns = [
        MappedColumn(column="station", role=ColumnRole.STATION),
        MappedColumn(column="easting", role=ColumnRole.EASTING),
        MappedColumn(column="northing", role=ColumnRole.NORTHING),
        MappedColumn(column="sampled_at", role=ColumnRole.TIMESTAMP),
        MappedColumn(column="parameter", role=ColumnRole.PARAMETER),
        MappedColumn(column="value", role=ColumnRole.VALUE),
        MappedColumn(column="unit", role=ColumnRole.UNIT),
    ]
    without_crs = ColumnMapping.model_validate(
        {"layout": LayoutKind.LONG, "columns": [c.model_dump() for c in columns]}
    )
    with pytest.raises(ValidationError) as error:
        validate_mapping(without_crs, fields=fields)
    _assert_structural_error(error, "CRS")

    with_crs = ColumnMapping.model_validate(
        {
            "layout": LayoutKind.LONG,
            "columns": [c.model_dump() for c in columns],
            "source_crs": "EPSG:32644",
        }
    )
    validation = validate_mapping(
        with_crs,
        fields=fields,
        numeric_fields=frozenset({"easting", "northing", "value"}),
    )
    assert validation.warnings == ()


def test_validate_mapping_warns_when_geographic_and_projected_coordinates_mix() -> None:
    fields = (*LONG_FIELDS, "easting", "northing")
    columns = list(long_mapping().columns)[:-1]
    columns.extend(
        [
            MappedColumn(column="easting", role=ColumnRole.EASTING),
            MappedColumn(column="northing", role=ColumnRole.NORTHING),
        ]
    )
    mapping = ColumnMapping.model_validate(
        {
            "layout": LayoutKind.LONG,
            "columns": [c.model_dump() for c in columns],
            "source_crs": "EPSG:32644",
        }
    )
    validation = validate_mapping(
        mapping,
        fields=fields,
        numeric_fields=frozenset({"latitude", "longitude", "value", "easting", "northing"}),
    )
    assert any("projected" in warning for warning in validation.warnings)


def test_validate_mapping_warns_about_evidence_contradictions() -> None:
    validation = validate_mapping(
        long_mapping(),
        fields=LONG_FIELDS,
        numeric_fields=frozenset(),
        date_fields=frozenset({"value"}),
    )
    assert any("coordinate column 'latitude'" in warning for warning in validation.warnings)
    assert any("looked like dates" in warning for warning in validation.warnings)


def test_validate_mapping_rejects_wide_only_roles_on_a_wide_table() -> None:
    columns = [
        MappedColumn(column="date", role=ColumnRole.TIMESTAMP),
        MappedColumn(column="St. A", role=ColumnRole.VALUE, station_label="St. A"),
        MappedColumn(column="unit", role=ColumnRole.UNIT),
    ]
    mapping = ColumnMapping.model_validate(
        {"layout": LayoutKind.WIDE, "wide_axis": "stations", "columns": columns}
    )
    with pytest.raises(ValidationError) as error:
        validate_mapping(mapping, fields=("date", "St. A", "unit"))
    _assert_structural_error(error, "wide table")


def test_validate_mapping_requires_station_labels_on_station_axis_columns() -> None:
    columns = [
        MappedColumn(column="date", role=ColumnRole.TIMESTAMP),
        MappedColumn(column="St. A", role=ColumnRole.VALUE),
    ]
    mapping = ColumnMapping.model_validate(
        {"layout": LayoutKind.WIDE, "wide_axis": "stations", "columns": columns}
    )
    with pytest.raises(ValidationError) as error:
        validate_mapping(mapping, fields=("date", "St. A"))
    _assert_structural_error(error, "station label")


def test_validate_mapping_requires_a_parameter_source_for_station_axis_values() -> None:
    columns = [
        MappedColumn(column="date", role=ColumnRole.TIMESTAMP),
        MappedColumn(column="St. A", role=ColumnRole.VALUE, station_label="St. A"),
    ]
    mapping = ColumnMapping.model_validate(
        {"layout": LayoutKind.WIDE, "wide_axis": "stations", "columns": columns}
    )
    with pytest.raises(ValidationError) as error:
        validate_mapping(mapping, fields=("date", "St. A"))
    _assert_structural_error(error, "parameter")


def test_validate_mapping_accepts_a_complete_station_axis_mapping() -> None:
    columns = [
        MappedColumn(column="date", role=ColumnRole.TIMESTAMP),
        MappedColumn(column="St. A", role=ColumnRole.VALUE, station_label="St. A"),
        MappedColumn(column="St. B", role=ColumnRole.VALUE, station_label="St. B"),
        MappedColumn(column="extra", role=ColumnRole.IGNORED),
    ]
    mapping = ColumnMapping.model_validate(
        {
            "layout": LayoutKind.WIDE,
            "wide_axis": "stations",
            "columns": columns,
            "default_parameter": "salinity",
        }
    )
    validation = validate_mapping(mapping, fields=("date", "St. A", "St. B", "extra"))
    assert validation.warnings == ()


def test_validate_mapping_requires_a_station_column_for_the_parameter_axis() -> None:
    columns = [
        MappedColumn(column="date", role=ColumnRole.TIMESTAMP),
        MappedColumn(column="salinity", role=ColumnRole.VALUE, parameter_label="salinity"),
    ]
    mapping = ColumnMapping.model_validate(
        {"layout": LayoutKind.WIDE, "wide_axis": "parameters", "columns": columns}
    )
    with pytest.raises(ValidationError) as error:
        validate_mapping(mapping, fields=("date", "salinity"))
    _assert_structural_error(error, "station column")


def test_resolve_mapping_builds_the_lookup_structures() -> None:
    mapping = long_mapping()
    resolved = resolve_mapping(mapping, fields=LONG_FIELDS, has_header=True)
    assert resolved.role_of("station") is ColumnRole.STATION
    assert resolved.role_of("notes") is ColumnRole.IGNORED
    assert resolved.role_of("not_present") is ColumnRole.IGNORED
    assert resolved.field_of_role(ColumnRole.TIMESTAMP) == "sampled_at"
    assert resolved.field_of_role(ColumnRole.VALUE) == "value"
    assert resolved.field_of_role(ColumnRole.SECTOR) is None
    assert resolved.long_row_offset == 2
    assert resolved.wide_value_columns == ()


def test_resolve_mapping_resolves_the_long_row_offset_without_a_header() -> None:
    resolved = resolve_mapping(long_mapping(), fields=LONG_FIELDS, has_header=False)
    assert resolved.long_row_offset == 1


def test_propose_mapping_assigns_roles_from_header_names_and_evidence() -> None:
    proposal = propose_mapping(
        LONG_FIELDS,
        numeric_fields=frozenset({"latitude", "longitude", "value"}),
        date_fields=frozenset({"sampled_at"}),
        layout=LayoutKind.LONG,
    )
    roles = {item.column: item.role for item in proposal.mapping.columns}
    assert roles == {
        "station": ColumnRole.STATION,
        "latitude": ColumnRole.LATITUDE,
        "longitude": ColumnRole.LONGITUDE,
        "sampled_at": ColumnRole.TIMESTAMP,
        "parameter": ColumnRole.PARAMETER,
        "value": ColumnRole.VALUE,
        "unit": ColumnRole.UNIT,
        "qualifier": ColumnRole.QUALIFIER,
        "depth_m": ColumnRole.DEPTH,
        "notes": ColumnRole.IGNORED,
    }
    assert proposal.warnings == ()


def test_propose_mapping_is_deterministic() -> None:
    first = propose_mapping(
        LONG_FIELDS,
        numeric_fields=frozenset({"latitude", "longitude", "value"}),
        date_fields=frozenset({"sampled_at"}),
        layout=LayoutKind.LONG,
    )
    second = propose_mapping(
        LONG_FIELDS,
        numeric_fields=frozenset({"latitude", "longitude", "value"}),
        date_fields=frozenset({"sampled_at"}),
        layout=LayoutKind.LONG,
    )
    assert first == second


def test_propose_mapping_names_positional_columns_without_a_header() -> None:
    proposal = propose_mapping(
        ("column_1", "column_2", "column_3"),
        numeric_fields=frozenset({"column_2"}),
        date_fields=frozenset(),
        layout=LayoutKind.LONG,
    )
    roles = {item.column: item.role for item in proposal.mapping.columns}
    assert roles == {
        "column_1": ColumnRole.IGNORED,
        "column_2": ColumnRole.VALUE,
        "column_3": ColumnRole.IGNORED,
    }
    assert any("timestamp" in warning for warning in proposal.warnings)
    assert any("parameter" in warning for warning in proposal.warnings)
    assert any("unit" in warning for warning in proposal.warnings)


def test_propose_mapping_wide_defaults_to_the_station_axis() -> None:
    fields = ("date", "Outer Channel", "Central Sector", "Northern Sector")
    proposal = propose_mapping(
        fields,
        numeric_fields=frozenset({"Outer Channel", "Central Sector", "Northern Sector"}),
        date_fields=frozenset({"date"}),
        layout=LayoutKind.WIDE,
    )
    assert proposal.mapping.wide_axis == "stations"
    value_columns = [item for item in proposal.mapping.columns if item.role is ColumnRole.VALUE]
    assert [(item.column, item.station_label) for item in value_columns] == [
        ("Outer Channel", "Outer Channel"),
        ("Central Sector", "Central Sector"),
        ("Northern Sector", "Northern Sector"),
    ]
    assert any("axis was assumed" in warning for warning in proposal.warnings)
    assert any("parameter" in warning for warning in proposal.warnings)


def test_propose_mapping_wide_honors_a_declared_parameter_axis() -> None:
    fields = ("date", "salinity", "temperature", "station")
    proposal = propose_mapping(
        fields,
        numeric_fields=frozenset({"salinity", "temperature"}),
        date_fields=frozenset({"date"}),
        layout=LayoutKind.WIDE,
        wide_axis="parameters",
    )
    roles = {item.column: item.role for item in proposal.mapping.columns}
    assert roles["station"] is ColumnRole.STATION
    assert roles["salinity"] is ColumnRole.VALUE
    assert roles["temperature"] is ColumnRole.VALUE
    value_columns = [item for item in proposal.mapping.columns if item.role is ColumnRole.VALUE]
    assert all(item.parameter_label == item.column for item in value_columns)
    assert proposal.mapping.wide_axis == "parameters"


def test_propose_mapping_never_names_one_column_twice() -> None:
    fields = ("sampled_at", "Central Sector", "value")
    proposal = propose_mapping(
        fields,
        numeric_fields=frozenset({"Central Sector", "value"}),
        date_fields=frozenset({"sampled_at"}),
        layout=LayoutKind.WIDE,
    )
    names = [item.column for item in proposal.mapping.columns]
    assert len(names) == len(set(names))
    assert set(names) == set(fields)


def test_propose_mapping_prefers_hinted_value_columns_with_weak_samples() -> None:
    proposal = propose_mapping(
        ("station", "value", "sampled_at", "notes"),
        numeric_fields=frozenset(),
        date_fields=frozenset({"sampled_at"}),
        layout=LayoutKind.WIDE,
        wide_axis="parameters",
    )
    roles = {item.column: item.role for item in proposal.mapping.columns}
    assert roles["value"] is ColumnRole.VALUE
    assert roles["station"] is ColumnRole.STATION


def test_an_incomplete_proposal_fails_validation_like_any_mapping() -> None:
    proposal = propose_mapping(
        ("station", "value", "sampled_at"),
        numeric_fields=frozenset({"value"}),
        date_fields=frozenset({"sampled_at"}),
        layout=LayoutKind.LONG,
    )
    with pytest.raises(ValidationError):
        validate_mapping(proposal.mapping, fields=("station", "value", "sampled_at"))
