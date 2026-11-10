"""Canonicalization of normalized long rows into canonical observations.

Every raw field is preserved beside its canonical form: the raw value text and
unit are stored on the observation next to the canonical value and unit, and
neither overwrites the other. A row that cannot become an observation at all —
an unparsable timestamp, or no usable coordinate — is not silently dropped: it
is returned as a skipped row with a coded reason, so the normalization report
can account for every input row.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime

from trendsmapp.constants import DEFAULT_ANALYSIS_CRS
from trendsmapp.domain.enums import QcFlagCode
from trendsmapp.domain.identifiers import validate_identifier
from trendsmapp.domain.models import Observation
from trendsmapp.domain.policies import status_for_flags
from trendsmapp.domain.units import UnitRegistry, get_unit_registry
from trendsmapp.errors import ValidationError
from trendsmapp.ingestion.chunking import TextBatch
from trendsmapp.ingestion.column_mapping import ColumnMapping
from trendsmapp.ingestion.sniffing import DecimalStyle
from trendsmapp.ingestion.wide_to_long import LONG_SCHEMA_FIELDS
from trendsmapp.normalization.coordinates import (
    CoordinateResult,
    normalize_projected,
    normalize_wgs84,
)
from trendsmapp.normalization.parameters import (
    Parameter,
    ParameterRegistry,
    get_parameter_registry,
    normalize_alias,
)
from trendsmapp.normalization.timestamps import parse_timestamp
from trendsmapp.normalization.units import normalize_unit, normalize_value
from trendsmapp.normalization.values import ValueParseResult, parse_value

__all__ = [
    "CanonicalizationResult",
    "NormalizedRow",
    "RowIssue",
    "SkippedRow",
    "canonicalize_row",
    "derive_station_key",
    "observation_id_for",
]

_FIELD = {name: index for index, name in enumerate(LONG_SCHEMA_FIELDS)}


@dataclass(frozen=True, slots=True)
class NormalizedRow:
    """One long-schema row with its missingness flags."""

    source_row: int
    source_sheet: str
    fields: tuple[str, ...]
    missing: tuple[bool, ...]

    @classmethod
    def from_batch(cls, batch: TextBatch) -> Iterator[NormalizedRow]:
        """Yield one normalized row per record of a long-schema batch."""
        for index, row in enumerate(batch.rows):
            source_row_text = row[_FIELD["source_row"]]
            yield cls(
                source_row=int(source_row_text) if source_row_text else 0,
                source_sheet=row[_FIELD["source_sheet"]],
                fields=row,
                missing=batch.missing[index],
            )

    def cell(self, name: str) -> str:
        """Return the text of one long-schema field."""
        return self.fields[_FIELD[name]]

    def is_missing(self, name: str) -> bool:
        """Return whether the source recorded no value for a field."""
        return self.missing[_FIELD[name]]


@dataclass(frozen=True, slots=True)
class RowIssue:
    """One coded problem found while canonicalizing a row."""

    code: str
    field: str
    message: str
    source_row: int


@dataclass(frozen=True, slots=True)
class SkippedRow:
    """A row that could not become an observation, with the reason."""

    source_row: int
    source_sheet: str
    reason: str
    field: str
    detail: str


@dataclass(frozen=True, slots=True)
class CanonicalizationResult:
    """The outcome of canonicalizing one row."""

    observation: Observation | None
    row: NormalizedRow
    issues: tuple[RowIssue, ...]
    skipped: SkippedRow | None


def derive_station_key(label: str) -> str:
    """Return the deterministic station key of a label.

    The key is the normalized label; station registration (which owns durable
    station ids and their coordinates) resolves labels to ids, and until then
    this key is what groups duplicates.
    """
    return normalize_alias(label)


def observation_id_for(
    *,
    dataset_version_id: str,
    source_sheet: str,
    source_row: int,
    station_key: str,
    parameter_id: str,
    sampled_at: datetime,
) -> str:
    """Return the deterministic observation id of one row.

    The id is a digest of everything that identifies the observation inside the
    dataset version, so re-running the same parse and mapping on the same bytes
    produces the same ids.
    """
    payload = (
        f"{dataset_version_id}|{source_sheet}|{source_row}|{station_key}|"
        f"{parameter_id}|{sampled_at.isoformat()}"
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]
    return validate_identifier("obs", f"obs_{digest}")


def canonicalize_row(
    row: NormalizedRow,
    *,
    mapping: ColumnMapping,
    dataset_id: str,
    dataset_version_id: str,
    decimal_style: DecimalStyle,
    analysis_crs: str = DEFAULT_ANALYSIS_CRS,
    parameter_registry: ParameterRegistry | None = None,
    unit_registry: UnitRegistry | None = None,
    station_coordinates: Mapping[str, CoordinateResult] | None = None,
) -> CanonicalizationResult:
    """Canonicalize one normalized row into an observation or a skipped row."""
    registry = parameter_registry or get_parameter_registry()
    units = unit_registry or get_unit_registry()
    issues: list[RowIssue] = []

    resolved_timestamp = _resolve_timestamp(row, mapping)
    if isinstance(resolved_timestamp, CanonicalizationResult):
        return resolved_timestamp
    sampled_at = resolved_timestamp

    parameter_label = row.cell("parameter")
    resolution = registry.resolve(parameter_label)
    parameter: Parameter | None = resolution.parameter
    if parameter is None:
        issues.append(
            RowIssue(
                code=QcFlagCode.UNKNOWN_PARAMETER.value,
                field="parameter",
                message=f"'{parameter_label}' is not a registered parameter.",
                source_row=row.source_row,
            )
        )
    parameter_id = parameter.id if parameter is not None else ""

    raw_value = row.cell("value")
    raw_unit = row.cell("unit")
    value_result = parse_value(raw_value, style=decimal_style)
    _flag_value_issue(row, value_result, raw_value, issues)
    canonical_value, canonical_unit, detection_limit, conversion_factor = _normalize_row_value(
        row, parameter, units, raw_unit, value_result, issues
    )

    coordinates = _resolve_coordinates(row, mapping, station_coordinates, analysis_crs, issues)
    if coordinates is None:
        return _skipped(
            row, "missing_coordinate", "latitude/longitude", "no usable coordinate for the row"
        )
    if coordinates.latitude is None or coordinates.longitude is None:
        reason = next(
            (
                i
                for i in coordinates.issues
                if "out_of_range" in i or "non_finite" in i or "invalid" in i
            ),
            "invalid_coordinate",
        )
        return _skipped(row, QcFlagCode.COORDINATE_OUT_OF_RANGE.value, "latitude/longitude", reason)

    depth = _parse_row_depth(row, issues)

    station_label = row.cell("station")
    station_key = derive_station_key(station_label)
    qc_flags = _flags_from_issues(issues)
    observation = Observation(
        observation_id=observation_id_for(
            dataset_version_id=dataset_version_id,
            source_sheet=row.source_sheet,
            source_row=row.source_row,
            station_key=station_key,
            parameter_id=parameter_id,
            sampled_at=sampled_at,
        ),
        dataset_id=dataset_id,
        dataset_version_id=dataset_version_id,
        source_row=row.source_row,
        source_sheet=row.source_sheet or None,
        station_id=f"stn_{hashlib.sha256(station_key.encode('utf-8')).hexdigest()[:24]}",
        station_label=station_label or None,
        latitude_wgs84=coordinates.latitude,
        longitude_wgs84=coordinates.longitude,
        x_projected_m=coordinates.x_projected_m,
        y_projected_m=coordinates.y_projected_m,
        source_crs=coordinates.source_crs,
        analysis_crs=coordinates.analysis_crs,
        sector=(row.cell("sector") or None) if not row.is_missing("sector") else None,
        sampled_at=sampled_at,
        sampling_depth_m=depth,
        parameter_id=parameter_id,
        parameter_label=parameter_label,
        raw_value=raw_value if not row.is_missing("value") else None,
        raw_unit=(raw_unit or None) if not row.is_missing("unit") else None,
        value_qualifier=value_result.qualifier,
        canonical_value=canonical_value,
        canonical_unit=canonical_unit,
        detection_limit=detection_limit,
        conversion_factor=conversion_factor,
        method_id=None,
        instrument_id=None,
        qc_status=status_for_flags(qc_flags),
        qc_flags=qc_flags,
        is_excluded=False,
        exclusion_reason=None,
        provenance_ids=(),
    )
    return CanonicalizationResult(
        observation=observation,
        row=row,
        issues=tuple(issues),
        skipped=None,
    )


def _resolve_timestamp(
    row: NormalizedRow, mapping: ColumnMapping
) -> datetime | CanonicalizationResult:
    """Parse the row timestamp, or return the skip result when it is unusable."""
    timestamp_text = row.cell("sampled_at")
    if row.is_missing("sampled_at") or not timestamp_text.strip():
        return _skipped(row, "missing_timestamp", "sampled_at", "the row has no timestamp")
    try:
        return parse_timestamp(
            timestamp_text,
            date_order=mapping.date_order,
            timezone_policy=mapping.timezone_policy,
            timezone_name=mapping.timezone_name,
        )
    except ValidationError as exc:
        reason = exc.details.get("reason", "unparsable_timestamp")
        code = {
            "empty_timestamp": QcFlagCode.MISSING_TIMESTAMP,
            "missing_offset": QcFlagCode.AMBIGUOUS_TIMESTAMP,
            "invalid_date": QcFlagCode.IMPOSSIBLE_TIMESTAMP,
            "invalid_time": QcFlagCode.IMPOSSIBLE_TIMESTAMP,
        }.get(reason, QcFlagCode.AMBIGUOUS_TIMESTAMP)
        return _skipped(row, code.value, "sampled_at", str(exc))


def _flag_value_issue(
    row: NormalizedRow, value_result: ValueParseResult, raw_value: str, issues: list[RowIssue]
) -> None:
    """Record the QC issue for an unparsable, missing, or non-finite value."""
    if value_result.reason == "missing_value":
        issues.append(
            RowIssue(
                code=QcFlagCode.MISSING_VALUE.value,
                field="value",
                message="the row has no value",
                source_row=row.source_row,
            )
        )
    elif value_result.reason == "non_finite":
        issues.append(
            RowIssue(
                code=QcFlagCode.NON_FINITE_VALUE.value,
                field="value",
                message=f"'{raw_value}' is not a finite number",
                source_row=row.source_row,
            )
        )
    elif value_result.reason is not None:
        issues.append(
            RowIssue(
                code="invalid_value",
                field="value",
                message=f"'{raw_value}' could not be parsed as a number ({value_result.reason})",
                source_row=row.source_row,
            )
        )


def _normalize_row_value(
    row: NormalizedRow,
    parameter: Parameter | None,
    units: UnitRegistry,
    raw_unit: str,
    value_result: ValueParseResult,
    issues: list[RowIssue],
) -> tuple[float | None, str | None, float | None, float | None]:
    """Normalize value and unit against the parameter registry.

    Returns ``(canonical_value, canonical_unit, detection_limit, conversion_factor)``.
    """
    if parameter is None:
        if not row.is_missing("unit") and raw_unit.strip():
            issues.append(
                RowIssue(
                    code=QcFlagCode.UNKNOWN_UNIT.value,
                    field="unit",
                    message=f"unit '{raw_unit}' cannot be checked without a known parameter",
                    source_row=row.source_row,
                )
            )
        return None, None, None, None
    unit_norm = normalize_unit(raw_unit, parameter=parameter, unit_registry=units)
    if not row.is_missing("unit") and unit_norm.issue:
        issues.append(
            RowIssue(
                code=(
                    QcFlagCode.UNKNOWN_UNIT.value
                    if unit_norm.issue == "unknown_unit"
                    else QcFlagCode.INCOMPATIBLE_UNIT.value
                ),
                field="unit",
                message=f"unit '{raw_unit}': {unit_norm.issue}",
                source_row=row.source_row,
            )
        )
    value_norm = normalize_value(value_result, unit_norm, parameter=parameter, unit_registry=units)
    for issue_text in value_norm.issues:
        issues.append(
            RowIssue(
                code="unit_conversion"
                if "case corrected" in issue_text
                else QcFlagCode.INCOMPATIBLE_UNIT.value,
                field="unit",
                message=issue_text,
                source_row=row.source_row,
            )
        )
    return (
        value_norm.canonical_value,
        value_norm.canonical_unit,
        value_norm.detection_limit,
        value_norm.conversion.factor if value_norm.conversion else None,
    )


def _parse_row_depth(row: NormalizedRow, issues: list[RowIssue]) -> float | None:
    """Parse the optional depth column, flagging non-finite values."""
    depth_text = row.cell("depth_m")
    if row.is_missing("depth_m") or not depth_text.strip():
        return None
    try:
        depth = float(depth_text)
        if not math.isfinite(depth):
            raise ValueError
    except ValueError:
        issues.append(
            RowIssue(
                code="invalid_depth",
                field="depth_m",
                message=f"'{depth_text}' is not a finite depth",
                source_row=row.source_row,
            )
        )
        return None
    return depth


def _resolve_coordinates(
    row: NormalizedRow,
    mapping: ColumnMapping,
    station_coordinates: Mapping[str, CoordinateResult] | None,
    analysis_crs: str,
    issues: list[RowIssue],
) -> CoordinateResult | None:
    """Resolve the coordinates of a row from its columns or its station."""
    lat_missing = row.is_missing("latitude")
    lon_missing = row.is_missing("longitude")
    if not lat_missing and not lon_missing:
        return normalize_wgs84(
            row.cell("latitude"), row.cell("longitude"), analysis_crs=analysis_crs
        )
    easting_missing = row.is_missing("easting")
    northing_missing = row.is_missing("northing")
    if not easting_missing and not northing_missing:
        source_crs = mapping.source_crs
        if not source_crs:
            issues.append(
                RowIssue(
                    code="missing_source_crs",
                    field="easting/northing",
                    message="projected coordinates require the source CRS in the mapping",
                    source_row=row.source_row,
                )
            )
            return None
        return normalize_projected(
            row.cell("easting"),
            row.cell("northing"),
            source_crs=source_crs,
            analysis_crs=analysis_crs,
        )
    station_label = row.cell("station")
    if station_coordinates:
        return station_coordinates.get(derive_station_key(station_label))
    return None


def _flags_from_issues(issues: list[RowIssue]) -> tuple[QcFlagCode, ...]:
    """Map canonicalization issues onto QC flags.

    Codes that are already flag codes pass through. ``invalid_value`` becomes
    ``INVALID_VALUE``. Codes with no flag equivalent (an invalid depth, a
    missing source CRS) stay in the normalization report only.
    """
    flags: list[QcFlagCode] = []
    for issue in issues:
        try:
            flags.append(QcFlagCode(issue.code))
        except ValueError:
            if issue.code == "invalid_value":
                flags.append(QcFlagCode.INVALID_VALUE)
    return tuple(dict.fromkeys(flags))


def _skipped(row: NormalizedRow, reason: str, field: str, detail: str) -> CanonicalizationResult:
    """Build the result for a row that cannot become an observation."""
    return CanonicalizationResult(
        observation=None,
        row=row,
        issues=(),
        skipped=SkippedRow(
            source_row=row.source_row,
            source_sheet=row.source_sheet,
            reason=reason,
            field=field,
            detail=detail,
        ),
    )
