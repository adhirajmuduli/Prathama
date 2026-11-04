"""Canonical domain models for scientific meaning.

These dataclasses describe the data itself. They are deliberately independent
of HTTP, SQLAlchemy, object storage, and the user interface: a repository or a
route translates between its own representation and these models, and the
models never import a framework. Every model validates its invariants when it
is constructed, so an invalid observation cannot exist in memory.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from trendsmapp.clock import ensure_utc
from trendsmapp.domain.enums import QcFlagCode, QcStatus, ValueQualifier
from trendsmapp.errors import DomainError

__all__ = [
    "ArtifactRecord",
    "Boundary",
    "DatasetVersion",
    "Method",
    "Observation",
    "Parameter",
    "Run",
    "Station",
]


def _require_finite(name: str, value: float) -> None:
    if not math.isfinite(value):
        raise DomainError(f"{name} must be a finite number.", details={"value": value})


@dataclass(frozen=True, slots=True)
class Observation:
    """One canonical environmental observation.

    The raw value and raw unit are preserved exactly as they were read. The
    canonical value and canonical unit are the normalized representation used
    by analyses. Both are stored side by side and neither overwrites the
    other.
    """

    observation_id: str
    dataset_id: str
    dataset_version_id: str
    source_row: int
    source_sheet: str | None
    station_id: str
    station_label: str | None
    latitude_wgs84: float
    longitude_wgs84: float
    x_projected_m: float | None
    y_projected_m: float | None
    source_crs: str
    analysis_crs: str
    sector: str | None
    sampled_at: datetime
    sampling_depth_m: float | None
    parameter_id: str
    parameter_label: str
    raw_value: float | str | None
    raw_unit: str | None
    value_qualifier: ValueQualifier
    canonical_value: float | None
    canonical_unit: str | None
    detection_limit: float | None
    method_id: str | None
    instrument_id: str | None
    qc_status: QcStatus
    qc_flags: tuple[QcFlagCode, ...]
    is_excluded: bool
    exclusion_reason: str | None
    provenance_ids: tuple[str, ...]
    conversion_factor: float | None = None

    def __post_init__(self) -> None:
        if self.source_row < 0:
            raise DomainError("The source row index cannot be negative.")
        _require_finite("latitude_wgs84", self.latitude_wgs84)
        _require_finite("longitude_wgs84", self.longitude_wgs84)
        if not -90.0 <= self.latitude_wgs84 <= 90.0:
            raise DomainError(
                "latitude_wgs84 must lie between -90 and 90 degrees.",
                details={"value": self.latitude_wgs84},
            )
        if not -180.0 <= self.longitude_wgs84 <= 180.0:
            raise DomainError(
                "longitude_wgs84 must lie between -180 and 180 degrees.",
                details={"value": self.longitude_wgs84},
            )
        if (self.x_projected_m is None) != (self.y_projected_m is None):
            raise DomainError("Projected coordinates must be supplied as a complete x/y pair.")
        if self.x_projected_m is not None and self.y_projected_m is not None:
            _require_finite("x_projected_m", self.x_projected_m)
            _require_finite("y_projected_m", self.y_projected_m)
        ensure_utc(self.sampled_at)
        if self.sampling_depth_m is not None:
            _require_finite("sampling_depth_m", self.sampling_depth_m)
        if self.canonical_value is not None:
            _require_finite("canonical_value", self.canonical_value)
        if self.detection_limit is not None:
            _require_finite("detection_limit", self.detection_limit)
            if self.detection_limit < 0:
                raise DomainError("A detection limit cannot be negative.")
        if (
            self.value_qualifier
            in {
                ValueQualifier.BELOW_DETECTION_LIMIT,
                ValueQualifier.NOT_DETECTED,
            }
            and self.detection_limit is None
        ):
            raise DomainError(
                f"A '{self.value_qualifier}' observation requires a detection limit.",
                details={"observation_id": self.observation_id},
            )
        if self.is_excluded and not self.exclusion_reason:
            raise DomainError(
                "An excluded observation must record the reason for exclusion.",
                details={"observation_id": self.observation_id},
            )

    @property
    def has_qc_findings(self) -> bool:
        """Return whether any quality-control flag was recorded."""
        return bool(self.qc_flags)


@dataclass(frozen=True, slots=True)
class Station:
    """A monitoring location and its coordinates."""

    station_id: str
    label: str | None
    latitude_wgs84: float
    longitude_wgs84: float
    x_projected_m: float | None = None
    y_projected_m: float | None = None
    source_crs: str = "EPSG:4326"
    analysis_crs: str = "EPSG:32644"
    sector: str | None = None
    first_sampled_at: datetime | None = None
    last_sampled_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_finite("latitude_wgs84", self.latitude_wgs84)
        _require_finite("longitude_wgs84", self.longitude_wgs84)
        if not -90.0 <= self.latitude_wgs84 <= 90.0:
            raise DomainError("latitude_wgs84 must lie between -90 and 90 degrees.")
        if not -180.0 <= self.longitude_wgs84 <= 180.0:
            raise DomainError("longitude_wgs84 must lie between -180 and 180 degrees.")


@dataclass(frozen=True, slots=True)
class Parameter:
    """A measured variable with its canonical unit."""

    parameter_id: str
    label: str
    canonical_unit: str | None
    dimension: str | None
    display_name: str | None = None
    physical_range: tuple[float, float] | None = None
    aliases: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.parameter_id:
            raise DomainError("A parameter requires an identifier.")
        if not self.label:
            raise DomainError("A parameter requires a label.")
        if self.physical_range is not None:
            lower, upper = self.physical_range
            if lower > upper:
                raise DomainError(
                    "A physical range must have a lower bound at or below its upper bound."
                )


@dataclass(frozen=True, slots=True)
class Method:
    """A laboratory or field method recorded as measurement metadata."""

    method_id: str
    label: str
    description: str | None = None
    reference: str | None = None


@dataclass(frozen=True, slots=True)
class Boundary:
    """A validated analysis boundary with its content hash."""

    boundary_id: str
    geojson: dict[str, Any]
    sha256: str
    source_crs: str = "EPSG:4326"
    is_repaired: bool = False
    repair_details: dict[str, Any] = field(default_factory=dict)
    attribution: str | None = None
    license: str | None = None

    def __post_init__(self) -> None:
        if not self.boundary_id:
            raise DomainError("A boundary requires an identifier.")
        if not self.sha256:
            raise DomainError("A boundary requires the hash of its canonical geometry.")


@dataclass(frozen=True, slots=True)
class DatasetVersion:
    """An immutable, sealed version of a normalized dataset."""

    dataset_version_id: str
    dataset_id: str
    schema_version: str
    normalized_artifact_id: str
    normalized_sha256: str
    row_count: int
    parameter_ids: tuple[str, ...]
    station_ids: tuple[str, ...]
    first_sampled_at: datetime | None = None
    last_sampled_at: datetime | None = None
    boundary_id: str | None = None
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.row_count < 0:
            raise DomainError("A dataset version cannot have a negative row count.")


@dataclass(frozen=True, slots=True)
class Run:
    """One analysis execution bound to a dataset version and a recipe."""

    run_id: str
    dataset_version_id: str
    recipe_hash: str
    dataset_sha256: str
    boundary_sha256: str | None
    seed: int
    application_version: str
    schema_version: str
    created_at: datetime
    job_id: str | None = None

    def __post_init__(self) -> None:
        if not self.recipe_hash:
            raise DomainError("A run requires the hash of the recipe that produced it.")
        if not self.dataset_sha256:
            raise DomainError("A run requires the hash of the dataset version it used.")


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    """Metadata for one immutable stored artifact."""

    artifact_id: str
    kind: str
    sha256: str
    size_bytes: int
    content_type: str
    schema_version: str
    created_at: datetime
    storage_key: str
    run_id: str | None = None
    dataset_version_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.size_bytes < 0:
            raise DomainError("An artifact cannot have a negative size.")
        if not self.sha256:
            raise DomainError("An artifact requires the SHA-256 hash of its bytes.")
