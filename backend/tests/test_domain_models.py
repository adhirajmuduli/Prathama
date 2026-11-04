"""Tests for domain models, policies, units, identifiers, clock, and migrations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from trendsmapp.clock import FrozenClock, SystemClock, ensure_utc, isoformat_z
from trendsmapp.contracts.migrations import Migration, MigrationRegistry, migrate_artifact_document
from trendsmapp.contracts.versions import ARTIFACT_SCHEMA_VERSION
from trendsmapp.domain.enums import (
    CensoringPolicy,
    DuplicatePolicy,
    ExtrapolationPolicy,
    QcFlagCode,
    QcStatus,
    ValueQualifier,
)
from trendsmapp.domain.identifiers import (
    OBSERVATION_ID_PATTERN,
    new_artifact_id,
    new_dataset_id,
    new_dataset_version_id,
    new_job_id,
    new_observation_id,
    new_parameter_id,
    new_provenance_id,
    new_run_id,
    new_station_id,
    new_upload_id,
    validate_identifier,
)
from trendsmapp.domain.models import (
    ArtifactRecord,
    Boundary,
    DatasetVersion,
    Method,
    Observation,
    Parameter,
    Run,
    Station,
)
from trendsmapp.domain.policies import (
    CensoringPolicySpec,
    DuplicatePolicySpec,
    ExclusionPolicySpec,
    ExtrapolationPolicySpec,
)
from trendsmapp.domain.units import UnitRegistry, get_unit_registry
from trendsmapp.errors import CompatibilityError, DomainError, ValidationError
from trendsmapp.version import build_metadata, schema_version

SAMPLED_AT = datetime(2026, 1, 15, 6, 30, tzinfo=UTC)


def _observation(**overrides: object) -> Observation:
    defaults: dict[str, object] = {
        "observation_id": new_observation_id(),
        "dataset_id": new_dataset_id(),
        "dataset_version_id": new_dataset_version_id(),
        "source_row": 0,
        "source_sheet": None,
        "station_id": new_station_id(),
        "station_label": "Station 1",
        "latitude_wgs84": 19.7012,
        "longitude_wgs84": 85.2085,
        "x_projected_m": 612345.0,
        "y_projected_m": 2187654.0,
        "source_crs": "EPSG:4326",
        "analysis_crs": "EPSG:32644",
        "sector": "Outer",
        "sampled_at": SAMPLED_AT,
        "sampling_depth_m": 0.5,
        "parameter_id": new_parameter_id(),
        "parameter_label": "Salinity",
        "raw_value": 12.5,
        "raw_unit": "ppt",
        "value_qualifier": ValueQualifier.MEASURED,
        "canonical_value": 12.5,
        "canonical_unit": "psu",
        "detection_limit": None,
        "method_id": None,
        "instrument_id": None,
        "qc_status": QcStatus.PASS,
        "qc_flags": (),
        "is_excluded": False,
        "exclusion_reason": None,
        "provenance_ids": (),
    }
    defaults.update(overrides)
    return Observation(**defaults)  # type: ignore[arg-type]


def test_identifiers_are_prefixed_and_validated() -> None:
    dataset_id = new_dataset_id()
    assert dataset_id.startswith("ds_")
    assert new_dataset_version_id().startswith("dsv_")
    assert new_upload_id().startswith("upl_")
    assert new_job_id().startswith("job_")
    assert new_run_id().startswith("run_")
    assert new_station_id().startswith("stn_")
    assert new_parameter_id().startswith("par_")
    assert new_provenance_id().startswith("prv_")
    assert new_artifact_id().startswith("art_")
    assert OBSERVATION_ID_PATTERN.fullmatch(new_observation_id())

    assert validate_identifier("ds", dataset_id) == dataset_id
    with pytest.raises(DomainError):
        validate_identifier("unknown", dataset_id)
    with pytest.raises(DomainError):
        validate_identifier("ds", "not-a-dataset-id")


def test_observation_preserves_raw_and_canonical_values() -> None:
    observation = _observation()
    assert observation.raw_value == 12.5
    assert observation.raw_unit == "ppt"
    assert observation.canonical_value == 12.5
    assert observation.canonical_unit == "psu"
    assert observation.has_qc_findings is False
    flagged = _observation(qc_flags=(QcFlagCode.VALUE_ABOVE_PHYSICAL_RANGE,))
    assert flagged.has_qc_findings is True


def test_observation_rejects_invalid_coordinates_and_values() -> None:
    with pytest.raises(DomainError):
        _observation(source_row=-1)
    with pytest.raises(DomainError):
        _observation(latitude_wgs84=91.0)
    with pytest.raises(DomainError):
        _observation(longitude_wgs84=181.0)
    with pytest.raises(DomainError):
        _observation(latitude_wgs84=float("nan"))
    with pytest.raises(DomainError):
        _observation(x_projected_m=None)
    with pytest.raises(DomainError):
        _observation(canonical_value=float("inf"))
    with pytest.raises(DomainError):
        _observation(sampling_depth_m=float("nan"))


def test_observation_requires_a_detection_limit_for_censored_values() -> None:
    with pytest.raises(DomainError):
        _observation(value_qualifier=ValueQualifier.BELOW_DETECTION_LIMIT, raw_value=None)
    censored = _observation(
        value_qualifier=ValueQualifier.BELOW_DETECTION_LIMIT,
        raw_value=None,
        canonical_value=None,
        detection_limit=0.01,
    )
    assert censored.detection_limit == 0.01
    with pytest.raises(DomainError):
        _observation(detection_limit=-0.5)


def test_excluded_observations_must_record_a_reason() -> None:
    with pytest.raises(DomainError):
        _observation(is_excluded=True)
    excluded = _observation(is_excluded=True, exclusion_reason="outside boundary")
    assert excluded.exclusion_reason == "outside boundary"


def test_station_parameter_boundary_version_run_and_artifact_invariants() -> None:
    with pytest.raises(DomainError):
        Station(station_id="stn_1", label=None, latitude_wgs84=100.0, longitude_wgs84=0.0)
    with pytest.raises(DomainError):
        Station(station_id="stn_1", label=None, latitude_wgs84=0.0, longitude_wgs84=200.0)

    with pytest.raises(DomainError):
        Parameter(parameter_id="", label="Salinity", canonical_unit="psu", dimension=None)
    with pytest.raises(DomainError):
        Parameter(parameter_id="par_1", label="", canonical_unit="psu", dimension=None)
    with pytest.raises(DomainError):
        Parameter(
            parameter_id="par_1",
            label="Salinity",
            canonical_unit="psu",
            dimension=None,
            physical_range=(10.0, 1.0),
        )

    with pytest.raises(DomainError):
        Boundary(boundary_id="", geojson={}, sha256="a" * 64)
    with pytest.raises(DomainError):
        Boundary(boundary_id="boundary-1", geojson={}, sha256="")

    with pytest.raises(DomainError):
        DatasetVersion(
            dataset_version_id="dsv_1",
            dataset_id="ds_1",
            schema_version="1.0.0",
            normalized_artifact_id="art_1",
            normalized_sha256="a" * 64,
            row_count=-1,
            parameter_ids=(),
            station_ids=(),
        )

    with pytest.raises(DomainError):
        Run(
            run_id="run_1",
            dataset_version_id="dsv_1",
            recipe_hash="",
            dataset_sha256="a" * 64,
            boundary_sha256=None,
            seed=1,
            application_version="0.1.0",
            schema_version="1.0.0",
            created_at=SAMPLED_AT,
        )
    with pytest.raises(DomainError):
        Run(
            run_id="run_1",
            dataset_version_id="dsv_1",
            recipe_hash="a" * 64,
            dataset_sha256="",
            boundary_sha256=None,
            seed=1,
            application_version="0.1.0",
            schema_version="1.0.0",
            created_at=SAMPLED_AT,
        )

    with pytest.raises(DomainError):
        ArtifactRecord(
            artifact_id="art_1",
            kind="datasets",
            sha256="a" * 64,
            size_bytes=-1,
            content_type="application/x",
            schema_version="1.0.0",
            created_at=SAMPLED_AT,
            storage_key="datasets/aa/file",
        )
    with pytest.raises(DomainError):
        ArtifactRecord(
            artifact_id="art_1",
            kind="datasets",
            sha256="",
            size_bytes=1,
            content_type="application/x",
            schema_version="1.0.0",
            created_at=SAMPLED_AT,
            storage_key="datasets/aa/file",
        )

    method = Method(method_id="method-grab", label="Grab sampling")
    assert method.reference is None


def test_duplicate_policy_cannot_resolve_an_error_policy() -> None:
    spec = DuplicatePolicySpec(policy=DuplicatePolicy.ERROR)
    with pytest.raises(ValueError, match="error"):
        spec.choose([1, 2])
    with pytest.raises(ValueError, match="candidate"):
        DuplicatePolicySpec().choose([])
    assert DuplicatePolicySpec(policy=DuplicatePolicy.KEEP_MOST_COMPLETE).choose([4, 2, 9]) == 4


def test_exclusion_and_censoring_policies_reject_unknown_values() -> None:
    with pytest.raises(ValueError, match="Unknown exclusion policy"):
        ExclusionPolicySpec(policy="unknown").should_exclude(QcStatus.FAIL, frozenset())
    with pytest.raises(ValueError, match="Unknown censoring policy"):
        CensoringPolicySpec(policy="unknown").apply(None, 0.01)
    assert CensoringPolicySpec(policy=CensoringPolicy.SUBSTITUTE_ZERO).apply(None, 0.01) == 0.0
    assert ExtrapolationPolicySpec(policy=ExtrapolationPolicy.NONE).allows_extrapolation is False
    assert ExtrapolationPolicySpec(policy=ExtrapolationPolicy.LINEAR).allows_extrapolation is True


def test_unit_registry_converts_checks_dimensions_and_reports_failures() -> None:
    registry = UnitRegistry()
    assert registry.canonical_name("mg") == "milligram"
    assert registry.dimension_signature("mg/L") == "[mass] / [length] ** 3"
    assert registry.dimension_signature("percent") == "dimensionless"
    assert registry.to_base_units(1.0, "g") == pytest.approx(0.001)
    assert registry.are_convertible("mg", "g") is True
    assert registry.are_convertible("mg", "m") is False
    assert registry.is_known("milligram") is True
    assert registry.is_known("not-a-unit") is False

    with pytest.raises(ValidationError):
        registry.convert(1.0, "mg", "m")
    with pytest.raises(ValidationError):
        registry.convert(1.0, "not-a-unit", "g")
    assert get_unit_registry() is get_unit_registry()


def test_frozen_clock_is_deterministic() -> None:
    clock = FrozenClock(SAMPLED_AT)
    assert clock.now() == SAMPLED_AT
    clock.advance(timedelta(hours=2))
    assert clock.now() == SAMPLED_AT + timedelta(hours=2)
    clock.set(SAMPLED_AT)
    assert clock.now() == SAMPLED_AT
    assert SystemClock().now().tzinfo is UTC
    assert isoformat_z(SAMPLED_AT) == "2026-01-15T06:30:00Z"
    with pytest.raises(ValueError, match="timezone-aware"):
        ensure_utc(datetime(2026, 1, 1))


def test_build_metadata_is_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRENDSMAPP_BUILD_COMMIT", "abc123")
    monkeypatch.setenv("TRENDSMAPP_BUILD_TIMESTAMP", "2026-01-01T00:00:00Z")
    monkeypatch.delenv("TRENDSMAPP_BUILD_BUILDER", raising=False)
    metadata = build_metadata()
    assert metadata.commit == "abc123"
    assert metadata.built_at == "2026-01-01T00:00:00Z"
    assert metadata.builder is None
    assert metadata.as_dict()["commit"] == "abc123"
    assert schema_version() == ARTIFACT_SCHEMA_VERSION


def _rename_unit(document: dict[str, object]) -> dict[str, object]:
    document["unit"] = "psu"
    return document


def test_migration_registry_rejects_unsupported_targets_and_downgrades() -> None:
    registry = MigrationRegistry("artifact", baseline_version="1.0.0")
    registry.register(Migration("1.0.0", "1.1.0", _rename_unit))
    assert registry.head_version == "1.1.0"
    assert registry.versions == ("1.0.0", "1.1.0")
    assert len(registry.path_to("1.1.0")) == 1
    assert registry.path_to("1.0.0") == ()
    with pytest.raises(CompatibilityError):
        registry.path_to("2.0.0")

    with pytest.raises(CompatibilityError):
        registry.migrate({"schema_version": "1.1.0"}, "1.0.0")
    with pytest.raises(CompatibilityError):
        registry.migrate({}, "1.0.0")
    with pytest.raises(CompatibilityError):
        registry.migrate({"schema_version": "not-a-version"}, "1.0.0")
    with pytest.raises(CompatibilityError):
        registry.migrate({"schema_version": "0.9.0"}, "1.1.0")

    migrated = registry.migrate({"schema_version": "1.0.0", "value": 1}, "1.1.0")
    assert migrated["schema_version"] == "1.1.0"
    assert migrated["unit"] == "psu"

    repeated = registry.migrate(migrated, "1.1.0")
    assert repeated == migrated


def test_artifact_document_migration_is_idempotent_at_the_current_version() -> None:
    document = {"schema_version": ARTIFACT_SCHEMA_VERSION, "value": 1}
    migrated = migrate_artifact_document(document, ARTIFACT_SCHEMA_VERSION)
    assert migrated == document
    assert migrate_artifact_document(migrated, ARTIFACT_SCHEMA_VERSION) == migrated
