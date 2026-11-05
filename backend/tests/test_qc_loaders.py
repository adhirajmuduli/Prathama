"""Negative-path tests for the QC resource loaders."""

from __future__ import annotations

import pytest

import trendsmapp.resources as resources_module
from trendsmapp.errors import ValidationError
from trendsmapp.normalization.parameters import get_parameter_registry
from trendsmapp.qc.ranges import QC_RANGES_RESOURCE, _load, get_qc_ranges


def _ranges_document(**overrides: object) -> dict[str, object]:
    document: dict[str, object] = {
        "schema_version": "1.0.0",
        "plausibility_ranges": {"dissolved_oxygen": [0.0, 30.0]},
        "detection_limits": {"dissolved_oxygen": 0.01},
    }
    document.update(overrides)
    return document


def _load_with(monkeypatch: pytest.MonkeyPatch, document: object) -> None:
    monkeypatch.setattr(resources_module, "load_yaml_resource", lambda name: document)
    import trendsmapp.qc.ranges as ranges_module

    monkeypatch.setattr(ranges_module, "load_yaml_resource", resources_module.load_yaml_resource)
    _load(get_parameter_registry())


def test_qc_ranges_loads_and_is_cached() -> None:
    ranges = get_qc_ranges()
    assert ranges.plausibility_range("dissolved_oxygen") == (0.0, 30.0)
    assert ranges.detection_limit("dissolved_oxygen") == pytest.approx(0.01)
    assert ranges.plausibility_range("unknown_param") is None
    assert get_qc_ranges() is ranges or get_qc_ranges() == ranges


@pytest.mark.parametrize(
    ("document", "needle"),
    [
        (_ranges_document(plausibility_ranges="nope"), "plausibility_ranges"),
        (_ranges_document(plausibility_ranges={}), "plausibility_ranges"),
        (_ranges_document(detection_limits="nope"), "detection_limits"),
        (
            _ranges_document(plausibility_ranges={"ghost": [0.0, 1.0]}),
            "not in the parameter registry",
        ),
        (_ranges_document(plausibility_ranges={"dissolved_oxygen": "nope"}), "pair of numbers"),
        (_ranges_document(plausibility_ranges={"dissolved_oxygen": [1]}), "pair of numbers"),
        (_ranges_document(plausibility_ranges={"dissolved_oxygen": [30.0, 0.0]}), "inverted"),
        (
            _ranges_document(plausibility_ranges={"dissolved_oxygen": [True, 1.0]}),
            "pair of numbers",
        ),
        (_ranges_document(detection_limits={"ghost": 0.1}), "not in the parameter registry"),
        (_ranges_document(detection_limits={"dissolved_oxygen": "high"}), "positive number"),
        (_ranges_document(detection_limits={"dissolved_oxygen": -1}), "positive number"),
        (_ranges_document(detection_limits={"dissolved_oxygen": True}), "positive number"),
    ],
)
def test_qc_ranges_loader_rejects_broken_documents(
    monkeypatch: pytest.MonkeyPatch, document: object, needle: str
) -> None:
    with pytest.raises(ValidationError) as error:
        _load_with(monkeypatch, document)
    assert needle in str(error.value)


def test_qc_ranges_resource_name_is_stable() -> None:
    assert QC_RANGES_RESOURCE == "qc_ranges.v1.yaml"
