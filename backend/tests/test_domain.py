"""Tests for the domain models, policies, units, and provenance."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from trendsmapp.domain.enums import (
    CensoringPolicy,
    DuplicatePolicy,
    ExclusionPolicy,
    ExtrapolationPolicy,
    QcFlagCode,
    QcStatus,
    ValueQualifier,
)
from trendsmapp.domain.models import Observation
from trendsmapp.domain.policies import (
    CensoringPolicySpec,
    DuplicatePolicySpec,
    ExclusionPolicySpec,
    ExtrapolationPolicySpec,
)
from trendsmapp.domain.provenance import ProvenanceCollector, TransformationRecord
from trendsmapp.domain.units import UnitRegistry
from trendsmapp.errors import DomainError, ValidationError

SAMPLED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def _observation(**overrides: object) -> Observation:
    values: dict[str, object] = {
        "observation_id": "obs_" + "a" * 32,
        "dataset_id": "ds_" + "b" * 32,
        "dataset_version_id": "dsv_" + "c" * 32,
        "source_row": 0,
        "source_sheet": None,
        "station_id": "stn_" + "d" * 32,
        "station_label": None,
        "latitude_wgs84": 19.5,
        "longitude_wgs84": 85.1,
        "x_projected_m": 300000.0,
        "y_projected_m": 2200000.0,
        "source_crs": "EPSG:4326",
        "analysis_crs": "EPSG:32644",
        "sector": None,
        "sampled_at": SAMPLED_AT,
        "sampling_depth_m": None,
        "parameter_id": "par_" + "e" * 32,
        "parameter_label": "chlorophyll",
        "raw_value": 2.1,
        "raw_unit": "mg/L",
        "value_qualifier": ValueQualifier.MEASURED,
        "canonical_value": 2.1,
        "canonical_unit": "mg/L",
        "detection_limit": None,
        "method_id": None,
        "instrument_id": None,
        "qc_status": QcStatus.NOT_EVALUATED,
        "qc_flags": (),
        "is_excluded": False,
        "exclusion_reason": None,
        "provenance_ids": (),
    }
    values.update(overrides)
    return Observation(**values)  # type: ignore[arg-type]


def test_observation_accepts_a_valid_record() -> None:
    observation = _observation()
    assert observation.canonical_value == 2.1
    assert not observation.has_qc_findings


def test_observation_rejects_out_of_range_coordinates() -> None:
    with pytest.raises(DomainError):
        _observation(latitude_wgs84=95.0)
    with pytest.raises(DomainError):
        _observation(longitude_wgs84=-200.0)


def test_observation_rejects_partial_projected_pairs() -> None:
    with pytest.raises(DomainError):
        _observation(y_projected_m=None)


def test_observation_requires_a_detection_limit_for_censored_values() -> None:
    with pytest.raises(DomainError):
        _observation(value_qualifier=ValueQualifier.BELOW_DETECTION_LIMIT)


def test_observation_requires_a_reason_for_exclusion() -> None:
    with pytest.raises(DomainError):
        _observation(is_excluded=True)


def test_observation_rejects_naive_timestamps() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _observation(sampled_at=datetime(2026, 1, 1))


def test_duplicate_policy_selects_the_retained_row() -> None:
    keep_first = DuplicatePolicySpec(policy=DuplicatePolicy.KEEP_FIRST)
    keep_last = DuplicatePolicySpec(policy=DuplicatePolicy.KEEP_LAST)
    assert keep_first.choose([4, 2, 9]) == 2
    assert keep_last.choose([4, 2, 9]) == 9


def test_exclusion_policy_respects_the_selected_severity() -> None:
    none = ExclusionPolicySpec(policy=ExclusionPolicy.NONE)
    invalid = ExclusionPolicySpec(policy=ExclusionPolicy.EXCLUDE_INVALID)
    flagged = ExclusionPolicySpec(
        policy=ExclusionPolicy.EXCLUDE_FLAGGED,
        excluded_flags=frozenset({QcFlagCode.OUTSIDE_BOUNDARY}),
    )
    assert not none.should_exclude(QcStatus.FAIL, frozenset({QcFlagCode.OUTSIDE_BOUNDARY}))
    assert invalid.should_exclude(QcStatus.FAIL, frozenset())
    assert flagged.should_exclude(QcStatus.WARNING, frozenset({QcFlagCode.OUTSIDE_BOUNDARY}))
    assert not flagged.should_exclude(QcStatus.PASS, frozenset())


def test_censoring_policy_never_silently_returns_zero() -> None:
    keep = CensoringPolicySpec(policy=CensoringPolicy.KEEP_AS_LIMIT)
    half = CensoringPolicySpec(policy=CensoringPolicy.SUBSTITUTE_HALF)
    exclude = CensoringPolicySpec(policy=CensoringPolicy.EXCLUDE)
    assert keep.apply(None, 0.02) == 0.02
    assert half.apply(None, 0.02) == 0.01
    assert exclude.apply(None, 0.02) is None
    assert keep.apply(None, None) is None


def test_extrapolation_is_disabled_by_default() -> None:
    assert not ExtrapolationPolicySpec().allows_extrapolation
    assert ExtrapolationPolicySpec(policy=ExtrapolationPolicy.LINEAR).allows_extrapolation


def test_unit_conversion_is_dimension_checked() -> None:
    registry = UnitRegistry()
    conversion = registry.convert(1000.0, "mg", "g")
    assert conversion.value == pytest.approx(1.0)
    assert conversion.dimension == "[mass]"
    with pytest.raises(ValidationError):
        registry.convert(1.0, "mg", "m")


def test_unknown_units_are_rejected() -> None:
    registry = UnitRegistry()
    assert not registry.is_known("not-a-unit")
    with pytest.raises(ValidationError):
        registry.parse("")


def test_provenance_collector_records_events_in_order() -> None:
    collector = ProvenanceCollector()
    first = collector.record("ingested", input_artifact_ids=("art_" + "a" * 32,))
    second = collector.record(
        "normalized",
        input_artifact_ids=(first.provenance_id,),
        transformations=(
            TransformationRecord(name="unit_conversion", parameters={"factor": 0.001}),
        ),
    )
    assert len(collector.events) == 2
    assert collector.events[1].transformations[0].name == "unit_conversion"
    assert second.output_artifact_ids == ()
    documents = collector.as_documents()
    assert documents[0]["event_type"] == "ingested"
