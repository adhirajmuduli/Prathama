"""The versioned column mapping and its role resolution.

A mapping is the analyst's confirmed answer to one question: which column of
this file plays which role in the canonical observation model. The mapping is
a versioned contract document, so a stored dataset can always be traced back
to the mapping that produced it.

The module has three jobs:

- validate a mapping against the fields the parser actually found, with hard
  errors for structural impossibilities and warnings for evidence mismatches;
- resolve a mapping into the fast lookup structures the parser and the
  wide-to-long converter use;
- propose a mapping from the sniffer's evidence, as a starting point for the
  mapping interface. A proposal is a suggestion, never a confirmation: an
  incomplete proposal fails validation exactly like a wrong one.

A mapping never invents data. A wide matrix whose parameter is unknown cannot
be mapped, and the validation says so instead of choosing a label.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from trendsmapp.contracts.versions import ensure_supported_recipe_schema
from trendsmapp.domain.enums import (
    ColumnRole,
    DateOrder,
    DuplicatePolicy,
    LayoutKind,
    TimezonePolicy,
)
from trendsmapp.errors import ValidationError
from trendsmapp.ingestion.sniffing import (
    COORDINATE_NAME_HINTS,
    PARAMETER_NAME_HINTS,
    STATION_NAME_HINTS,
    TIMESTAMP_NAME_HINTS,
    VALUE_NAME_HINTS,
    normalize_header_name,
)

__all__ = [
    "MAPPING_SCHEMA_VERSION",
    "ColumnMapping",
    "MappedColumn",
    "MappingValidation",
    "ProposedMapping",
    "ResolvedMapping",
    "propose_mapping",
    "resolve_mapping",
    "validate_mapping",
]

#: Version of the mapping document contract.
MAPPING_SCHEMA_VERSION: Final[str] = "1.0.0"

#: Roles a wide table may carry. A wide cell cannot hold a qualifier, a unit,
#: a depth, or a sector of its own: those are per-observation attributes, and
#: the mapping carries them as column attributes instead.
_WIDE_ALLOWED_ROLES: Final[frozenset[ColumnRole]] = frozenset(
    {ColumnRole.TIMESTAMP, ColumnRole.VALUE, ColumnRole.STATION, ColumnRole.IGNORED}
)

#: Roles of which a long table needs at most one column.
_SINGLE_ROLES: Final[frozenset[ColumnRole]] = frozenset(
    {
        ColumnRole.STATION,
        ColumnRole.LATITUDE,
        ColumnRole.LONGITUDE,
        ColumnRole.EASTING,
        ColumnRole.NORTHING,
        ColumnRole.TIMESTAMP,
        ColumnRole.PARAMETER,
        ColumnRole.VALUE,
        ColumnRole.UNIT,
        ColumnRole.QUALIFIER,
        ColumnRole.DEPTH,
        ColumnRole.SECTOR,
    }
)

#: Header-name hints used to propose roles. They are deliberately broad; the
#: analyst confirms the proposal.
_TIMESTAMP_HINTS: Final[tuple[str, ...]] = (
    "sampled_at",
    "sample_date",
    "sampling_date",
    "observation_date",
    "timestamp",
    "datetime",
    "date",
    "time",
    "month",
)
_QUALIFIER_HINTS: Final[tuple[str, ...]] = ("qualifier", "quality_flag", "flag", "qc_flag")
_DEPTH_HINTS: Final[tuple[str, ...]] = ("depth_m", "depth", "z")
_SECTOR_HINTS: Final[tuple[str, ...]] = ("sector", "zone", "region")
_UNIT_HINTS: Final[tuple[str, ...]] = ("unit", "units", "uom")


class MappedColumn(BaseModel):
    """One column of the source table and the role it plays."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    column: str = Field(min_length=1)
    role: ColumnRole
    #: For a wide value column: the parameter this column holds.
    parameter_label: str | None = Field(default=None, min_length=1)
    #: For a wide value column: the station this column belongs to.
    station_label: str | None = Field(default=None, min_length=1)
    #: For a wide value column: the unit of every value in this column.
    unit: str | None = Field(default=None, min_length=1)


class ColumnMapping(BaseModel):
    """The versioned, confirmed mapping of one source table.

    The document is deliberately explicit about every convention that a value
    parser would otherwise have to guess: the date order, the timezone policy,
    and how duplicates are treated. Nothing in the canonical pipeline infers
    what this document can state.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = MAPPING_SCHEMA_VERSION
    layout: LayoutKind
    wide_axis: Literal["stations", "parameters"] | None = None
    columns: tuple[MappedColumn, ...] = Field(min_length=1)
    default_parameter: str | None = Field(default=None, min_length=1)
    default_unit: str | None = Field(default=None, min_length=1)
    source_crs: str | None = Field(default=None, min_length=1)
    date_order: DateOrder = DateOrder.DAY_FIRST
    timezone_policy: TimezonePolicy = TimezonePolicy.ASSUME_UTC
    timezone_name: str | None = Field(default=None, min_length=1)
    duplicate_policy: DuplicatePolicy = DuplicatePolicy.FLAG_ALL

    @model_validator(mode="after")
    def _validate_document(self) -> ColumnMapping:
        ensure_supported_recipe_schema(self.schema_version)
        if self.layout is LayoutKind.UNKNOWN:
            raise ValueError("A mapping must confirm a layout; 'unknown' cannot be mapped.")
        if self.layout is LayoutKind.WIDE and self.wide_axis is None:
            raise ValueError("A wide mapping must declare which axis the columns represent.")
        if self.layout is LayoutKind.LONG and self.wide_axis is not None:
            raise ValueError("A long mapping must not declare a wide axis.")
        if self.timezone_policy is TimezonePolicy.NAMED and not self.timezone_name:
            raise ValueError("A named timezone policy requires the timezone name.")
        if self.timezone_policy is not TimezonePolicy.NAMED and self.timezone_name:
            raise ValueError("A timezone name is only meaningful with the named policy.")
        return self


@dataclass(frozen=True, slots=True)
class MappingValidation:
    """The outcome of validating a mapping against one table."""

    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResolvedMapping:
    """The lookup structures the parser and the converter use."""

    mapping: ColumnMapping
    role_by_field: dict[str, ColumnRole]
    field_by_role: dict[ColumnRole, str]
    wide_value_columns: tuple[MappedColumn, ...]
    has_header: bool

    def role_of(self, field: str) -> ColumnRole:
        """Return the role of a field, defaulting to ignored."""
        return self.role_by_field.get(field, ColumnRole.IGNORED)

    def field_of_role(self, role: ColumnRole) -> str | None:
        """Return the field assigned to a single-occurrence role, when mapped.

        Wide value columns are not single occurrences; they are reachable
        through :attr:`wide_value_columns` in declared order.
        """
        return self.field_by_role.get(role)

    @property
    def long_row_offset(self) -> int:
        """Return the physical row number of the first data row.

        The offset makes ``source_row`` match what the analyst sees: a table
        with a header puts its first data row on physical row two.
        """
        return 2 if self.has_header else 1


@dataclass(frozen=True, slots=True)
class ProposedMapping:
    """A mapping proposal derived from the sniffer's evidence."""

    mapping: ColumnMapping
    warnings: tuple[str, ...]


def validate_mapping(
    mapping: ColumnMapping,
    *,
    fields: tuple[str, ...],
    numeric_fields: frozenset[str] = frozenset(),
    date_fields: frozenset[str] = frozenset(),
) -> MappingValidation:
    """Validate a mapping against the fields of one parsed table.

    ``numeric_fields`` and ``date_fields`` carry the sniffer's evidence about
    each column. A role that contradicts the evidence produces a warning,
    because a bounded sample can mislead; only structural impossibilities
    produce errors.
    """
    warnings: list[str] = []
    available = set(fields)
    seen_columns: set[str] = set()
    role_counts: dict[ColumnRole, list[str]] = {}
    for mapped in mapping.columns:
        if mapped.column not in available:
            raise ValidationError(
                f"The mapping names column '{mapped.column}', which the table does not have.",
                details={"column": mapped.column, "available_columns": sorted(available)},
            )
        if mapped.column in seen_columns:
            raise ValidationError(
                f"The mapping names column '{mapped.column}' more than once.",
                details={"column": mapped.column},
            )
        seen_columns.add(mapped.column)
        role_counts.setdefault(mapped.role, []).append(mapped.column)

    unassigned = sorted(available - seen_columns)
    if unassigned:
        warnings.append(f"Column(s) without a role were ignored: {', '.join(unassigned)}.")

    if mapping.layout is LayoutKind.LONG:
        warnings.extend(_validate_long(mapping, role_counts))
    else:
        warnings.extend(_validate_wide(mapping, role_counts))

    for role in (ColumnRole.VALUE, ColumnRole.TIMESTAMP):
        for column in role_counts.get(role, []):
            if role is ColumnRole.VALUE and column in date_fields and column not in numeric_fields:
                warnings.append(f"The value column '{column}' looked like dates in the sample.")
            if (
                role is ColumnRole.TIMESTAMP
                and column in numeric_fields
                and column not in date_fields
            ):
                warnings.append(f"The timestamp column '{column}' looked numeric in the sample.")
    for role in (ColumnRole.LATITUDE, ColumnRole.LONGITUDE):
        for column in role_counts.get(role, []):
            if column not in numeric_fields:
                warnings.append(
                    f"The coordinate column '{column}' did not look numeric in the "
                    "sample; the values should be checked during normalization."
                )
    return MappingValidation(warnings=tuple(warnings))


def _validate_long(mapping: ColumnMapping, role_counts: dict[ColumnRole, list[str]]) -> list[str]:
    """Enforce the structural rules of a long mapping.

    A structural impossibility raises; only evidence that a sample can
    legitimately contradict is returned as a warning.
    """
    errors: list[str] = []
    warnings: list[str] = []
    for role, columns in role_counts.items():
        if role in _SINGLE_ROLES and len(columns) > 1:
            errors.append(
                f"The role '{role.value}' is assigned to more than one column "
                f"({', '.join(columns)}); a long table maps each role once."
            )
    _require_exactly_one(role_counts, ColumnRole.TIMESTAMP, errors)
    _require_exactly_one(role_counts, ColumnRole.VALUE, errors)
    _require_exactly_one(role_counts, ColumnRole.UNIT, errors, required=False)

    has_station = ColumnRole.STATION in role_counts
    has_latitude = ColumnRole.LATITUDE in role_counts
    has_longitude = ColumnRole.LONGITUDE in role_counts
    has_easting = ColumnRole.EASTING in role_counts
    has_northing = ColumnRole.NORTHING in role_counts
    has_projected = has_easting and has_northing

    if not (has_station or (has_latitude and has_longitude) or has_projected):
        errors.append(
            "A long mapping needs a station column, a latitude and longitude "
            "pair, or an easting and northing pair."
        )
    if has_latitude != has_longitude:
        errors.append("Latitude and longitude must be mapped together.")
    if has_projected and not mapping.source_crs:
        errors.append("Projected coordinates require the source CRS in the mapping.")
    if has_projected and (has_latitude or has_longitude):
        warnings.append(
            "Both geographic and projected coordinates are mapped; the projected "
            "pair is authoritative and the geographic pair is carried as data."
        )
    if ColumnRole.UNIT not in role_counts and not mapping.default_unit:
        errors.append("A long mapping needs a unit column or a declared default unit.")
    if ColumnRole.PARAMETER not in role_counts and not mapping.default_parameter:
        errors.append(
            "A long mapping needs a parameter column or a declared default "
            "parameter, because every observation must name its parameter."
        )
    labelled = [item for item in mapping.columns if item.parameter_label or item.station_label]
    if labelled:
        warnings.append(
            "parameter_label and station_label are wide-value attributes; they "
            f"were declared on {', '.join(item.column for item in labelled)} and "
            "are ignored for a long table."
        )
    if errors:
        raise ValidationError(
            "The column mapping does not match the table.",
            details={"errors": errors},
        )
    return warnings


def _validate_wide(mapping: ColumnMapping, role_counts: dict[ColumnRole, list[str]]) -> list[str]:
    """Enforce the structural rules of a wide mapping.

    A structural impossibility raises; only evidence that a sample can
    legitimately contradict is returned as a warning.
    """
    errors: list[str] = []
    for role in role_counts:
        if role not in _WIDE_ALLOWED_ROLES:
            errors.append(
                f"The role '{role.value}' cannot be represented by a wide table; "
                "map the column as ignored or convert the table to long form."
            )
    _require_exactly_one(role_counts, ColumnRole.TIMESTAMP, errors)
    value_columns = role_counts.get(ColumnRole.VALUE, [])
    if not value_columns:
        errors.append("A wide mapping needs at least one value column.")
    if mapping.wide_axis == "parameters" and ColumnRole.STATION not in role_counts:
        errors.append("A wide table whose columns are parameters needs a station column.")
    if mapping.wide_axis == "stations":
        for mapped in mapping.columns:
            if mapped.role is not ColumnRole.VALUE:
                continue
            if not mapped.station_label:
                errors.append(
                    f"The wide value column '{mapped.column}' needs the station "
                    "label its header represents."
                )
            if not (mapped.parameter_label or mapping.default_parameter):
                errors.append(
                    f"The wide value column '{mapped.column}' needs a parameter "
                    "label or the table-wide parameter."
                )
    if mapping.wide_axis == "parameters":
        for mapped in mapping.columns:
            if mapped.role is ColumnRole.VALUE and not mapped.parameter_label:
                errors.append(
                    f"The wide value column '{mapped.column}' needs the parameter "
                    "label its header represents."
                )
    if errors:
        raise ValidationError(
            "The column mapping does not match the table.",
            details={"errors": errors},
        )
    return []


def _require_exactly_one(
    role_counts: dict[ColumnRole, list[str]],
    role: ColumnRole,
    errors: list[str],
    *,
    required: bool = True,
) -> None:
    """Append an error when a role is missing or duplicated."""
    columns = role_counts.get(role, [])
    if required and len(columns) != 1:
        errors.append(
            f"The role '{role.value}' must be assigned to exactly one column; found {len(columns)}."
        )
    if not required and len(columns) > 1:
        errors.append(
            f"The role '{role.value}' must be assigned to at most one column; found {len(columns)}."
        )


def resolve_mapping(
    mapping: ColumnMapping, *, fields: tuple[str, ...], has_header: bool
) -> ResolvedMapping:
    """Resolve a validated mapping into the parser's lookup structures.

    Every role except ``VALUE`` maps to exactly one field; that is enforced by
    :func:`validate_mapping` before resolution. Wide tables carry one value
    column per station or parameter, so their value columns are resolved as an
    ordered tuple instead of a single field.
    """
    role_by_field: dict[str, ColumnRole] = {}
    field_by_role: dict[ColumnRole, str] = {}
    for mapped in mapping.columns:
        role_by_field[mapped.column] = mapped.role
        if mapped.role in _SINGLE_ROLES:
            field_by_role.setdefault(mapped.role, mapped.column)
    wide_value_columns = tuple(
        item
        for item in mapping.columns
        if item.role is ColumnRole.VALUE and mapping.layout is LayoutKind.WIDE
    )
    return ResolvedMapping(
        mapping=mapping,
        role_by_field=role_by_field,
        field_by_role=field_by_role,
        wide_value_columns=wide_value_columns,
        has_header=has_header,
    )


def propose_mapping(
    fields: tuple[str, ...],
    *,
    numeric_fields: frozenset[str],
    date_fields: frozenset[str],
    layout: LayoutKind,
    wide_axis: Literal["stations", "parameters"] | None = None,
) -> ProposedMapping:
    """Propose a mapping from header names and column evidence.

    The proposal is deterministic: the same fields and the same evidence always
    produce the same proposal. It is not validated for completeness on purpose,
    because a proposal is the start of a conversation with the analyst, not a
    confirmed document.
    """
    normalized = {field: normalize_header_name(field) for field in fields}
    warnings: list[str] = []
    axis = wide_axis
    claimed: set[str] = set()
    columns: list[MappedColumn] = []

    def claim(field: str | None, role: ColumnRole, **attributes: str | None) -> None:
        """Assign a field to a role unless another role already claimed it.

        A header can suggest two roles at once — a station column named
        "Central Sector" also matches the sector hint. The first claim wins in
        a fixed order, and the losing hint simply has no effect, so a proposal
        can never name one column twice.
        """
        if field is None or field in claimed:
            return
        claimed.add(field)
        columns.append(MappedColumn(column=field, role=role, **attributes))

    def named(hints: tuple[str, ...]) -> str | None:
        for field in fields:
            if any(hint in normalized[field] for hint in hints):
                return field
        return None

    timestamp = named(TIMESTAMP_NAME_HINTS)
    if timestamp is None:
        timestamp = next((field for field in fields if field in date_fields), None)
    parameter = named(PARAMETER_NAME_HINTS)
    value = named(VALUE_NAME_HINTS)
    if value is None:
        value = next(
            (
                field
                for field in fields
                if field in numeric_fields
                and field not in {timestamp, parameter}
                and not any(hint in normalized[field] for hint in COORDINATE_NAME_HINTS)
            ),
            None,
        )
    station = named(STATION_NAME_HINTS)
    latitude = next(
        (field for field in fields if _matches(normalized[field], ("lat",))),
        None,
    )
    longitude = next(
        (field for field in fields if _matches(normalized[field], ("lon", "long"))),
        None,
    )
    unit = next(
        (field for field in fields if _matches(normalized[field], _UNIT_HINTS)),
        None,
    )
    qualifier = next(
        (field for field in fields if _matches(normalized[field], _QUALIFIER_HINTS)),
        None,
    )
    depth = next(
        (field for field in fields if _matches(normalized[field], _DEPTH_HINTS)),
        None,
    )
    sector = next(
        (field for field in fields if _matches(normalized[field], _SECTOR_HINTS)),
        None,
    )

    if timestamp is not None:
        claim(timestamp, ColumnRole.TIMESTAMP)
    else:
        warnings.append("No timestamp column could be proposed; map one explicitly.")
    if layout is not LayoutKind.WIDE:
        # A long layout, and an undetermined one, get a long-style proposal:
        # most tables are long, and an undetermined table must be mapped
        # explicitly anyway.
        if parameter is not None:
            claim(parameter, ColumnRole.PARAMETER)
        else:
            warnings.append(
                "No parameter column was found; declare the parameter this table holds or map one."
            )
        if value is not None:
            claim(value, ColumnRole.VALUE)
        else:
            warnings.append("No value column could be proposed; map one explicitly.")
        claim(station, ColumnRole.STATION)
        if latitude is not None and longitude is not None:
            claim(latitude, ColumnRole.LATITUDE)
            claim(longitude, ColumnRole.LONGITUDE)
        if unit is not None:
            claim(unit, ColumnRole.UNIT)
        else:
            warnings.append("No unit column was found; declare a default unit or map one.")
    else:
        axis = wide_axis or "stations"
        if wide_axis is None:
            warnings.append(
                "The wide axis was assumed to be 'stations'; confirm or correct it in the mapping."
            )
        value_fields = [
            field
            for field in fields
            if field in numeric_fields
            and field != timestamp
            and not any(hint in normalized[field] for hint in COORDINATE_NAME_HINTS)
        ]
        hinted_value = [
            field
            for field in fields
            if field != timestamp
            and _matches(normalized[field], VALUE_NAME_HINTS)
            and field not in value_fields
            and not any(hint in normalized[field] for hint in COORDINATE_NAME_HINTS)
        ]
        # A column whose header names the value role belongs in the value set
        # even when a small sample obscures its numericity: the name is
        # evidence the analyst sees and can correct, while omitting the column
        # silently loses a measurement axis.
        value_fields = value_fields + hinted_value
        if not value_fields:
            warnings.append("No numeric value columns could be proposed for the wide layout.")
        for field in value_fields:
            claim(
                field,
                ColumnRole.VALUE,
                station_label=field if axis == "stations" else None,
                parameter_label=field if axis == "parameters" else None,
            )
        if axis == "parameters":
            claim(station, ColumnRole.STATION)
        if axis == "stations":
            warnings.append(
                "Confirm the parameter this wide table holds; the proposal cannot "
                "derive it from the headers."
            )
    claim(qualifier, ColumnRole.QUALIFIER)
    claim(depth, ColumnRole.DEPTH)
    claim(sector, ColumnRole.SECTOR)
    for field in fields:
        if field not in claimed:
            claim(field, ColumnRole.IGNORED)
    if not columns:
        warnings.append("The table has no columns to map.")
    mapping = ColumnMapping(
        layout=layout if layout is not LayoutKind.UNKNOWN else LayoutKind.LONG,
        wide_axis=axis if layout is LayoutKind.WIDE else None,
        columns=tuple(columns),
    )
    return ProposedMapping(mapping=mapping, warnings=tuple(warnings))


def _matches(normalized: str, hints: tuple[str, ...]) -> bool:
    """Return whether a normalized header contains any hint."""
    return any(hint in normalized for hint in hints)
