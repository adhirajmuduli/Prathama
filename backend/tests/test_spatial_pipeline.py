"""End-to-end tests of the spatial pipeline over synthetic observations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from trendsmapp.domain.enums import QcStatus, SpatialMethod, ValueQualifier
from trendsmapp.domain.models import Observation
from trendsmapp.errors import ResourceLimitError
from trendsmapp.geospatial.boundary import load_default_boundary
from trendsmapp.spatial.base import SpatialMethodSpec
from trendsmapp.spatial.pipeline import SpatialRecipe, run_spatial_analysis

T0 = datetime(2024, 1, 15, 9, 30, tzinfo=UTC)

# Four stations inside the Chilika boundary.
STATIONS = [
    ("St. A", 85.4700, 19.7350),
    ("St. B", 85.4900, 19.7500),
    ("St. C", 85.5200, 19.8100),
    ("St. D", 85.4500, 19.7000),
]


def _observation(
    index: int,
    station: str,
    lon: float,
    lat: float,
    value: float,
    sampled_at: datetime,
    *,
    status: QcStatus = QcStatus.PASS,
) -> Observation:
    return Observation(
        observation_id=f"obs_{index:032d}",
        dataset_id="ds_test",
        dataset_version_id="dsv_test",
        source_row=index + 2,
        source_sheet=None,
        station_id=f"stn_{station}",
        station_label=station,
        latitude_wgs84=lat,
        longitude_wgs84=lon,
        x_projected_m=None,
        y_projected_m=None,
        source_crs="EPSG:4326",
        analysis_crs="EPSG:32644",
        sector=None,
        sampled_at=sampled_at,
        sampling_depth_m=0.5,
        parameter_id="dissolved_oxygen",
        parameter_label="dissolved_oxygen",
        raw_value=str(value),
        raw_unit="mg/L",
        value_qualifier=ValueQualifier.MEASURED,
        canonical_value=value,
        canonical_unit="mg/L",
        detection_limit=None,
        method_id=None,
        instrument_id=None,
        qc_status=status,
        qc_flags=(),
        is_excluded=False,
        exclusion_reason=None,
        provenance_ids=(),
    )


def _frame_observations(base_value: float, sampled_at: datetime) -> list[Observation]:
    return [
        _observation(i, name, lon, lat, base_value + i * 0.1, sampled_at)
        for i, (name, lon, lat) in enumerate(STATIONS)
    ]


def _sink() -> tuple[dict[str, bytes], callable]:
    store: dict[str, bytes] = {}

    def sink(kind: str, name: str, payload: bytes, content_type: str, metadata: dict) -> str:
        key = f"{kind}/{name}"
        store[key] = payload
        return key

    return store, sink


def _recipe(**overrides: object) -> SpatialRecipe:
    base: dict[str, object] = {
        "methods": (
            SpatialMethodSpec(method=SpatialMethod.IDW),
            SpatialMethodSpec(method=SpatialMethod.RBF),
        ),
        "grid_resolution_m": 2_000.0,
        "max_grid_cells": 250_000,
        "selection_rule": "best_rmse",
    }
    base.update(overrides)
    return SpatialRecipe(**base)  # type: ignore[arg-type]


def test_pipeline_runs_all_methods_and_stores_separate_outputs() -> None:
    boundary = load_default_boundary()
    observations = _frame_observations(6.8, T0) + _frame_observations(7.1, T0 + timedelta(days=28))
    store, sink = _sink()

    result = run_spatial_analysis(
        observations=observations,
        recipe=_recipe(),
        boundary=boundary,
        sink=sink,
    )

    assert len(result.frames) == 2
    assert result.boundary_sha256 == boundary.sha256
    assert result.grid_cells > 0
    assert result.masked_cells > 0

    for frame in result.frames:
        assert frame.skipped_reason is None
        assert frame.point_count == 4
        assert len(frame.methods) == 2
        methods = {m.method for m in frame.methods}
        assert methods == {SpatialMethod.IDW, SpatialMethod.RBF}
        for method_result in frame.methods:
            assert method_result.geotiff_key in store
            assert method_result.png_key in store
            assert method_result.metrics is not None
            assert method_result.metrics.fold_count == 4  # one fold per station
            assert method_result.metrics.valid_count == 4
        assert frame.mean_geotiff_key in store
        # The selection rule recorded a decision with evidence.
        assert len(frame.decisions) == 1
        decision = frame.decisions[0]
        assert decision.rule == "best_rmse"
        assert set(decision.evidence) == {"idw", "rbf"}
        assert decision.selected_method.value in {"idw", "rbf"}


def test_pipeline_is_deterministic() -> None:
    boundary = load_default_boundary()
    observations = _frame_observations(6.8, T0)
    store_a, sink_a = _sink()
    store_b, sink_b = _sink()
    recipe = _recipe()

    first = run_spatial_analysis(
        observations=observations, recipe=recipe, boundary=boundary, sink=sink_a
    )
    second = run_spatial_analysis(
        observations=observations, recipe=recipe, boundary=boundary, sink=sink_b
    )

    assert first.frames[0].methods[0].geotiff_sha256 == second.frames[0].methods[0].geotiff_sha256
    assert store_a.keys() == store_b.keys()
    for key in store_a:
        assert store_a[key] == store_b[key]


def test_frame_with_too_few_points_is_skipped_with_a_reason() -> None:
    boundary = load_default_boundary()
    observations = _frame_observations(6.8, T0)[:2]  # only two stations
    _store, sink = _sink()
    result = run_spatial_analysis(
        observations=observations, recipe=_recipe(), boundary=boundary, sink=sink
    )
    assert len(result.frames) == 1
    assert result.frames[0].skipped_reason is not None
    assert "required" in result.frames[0].skipped_reason
    assert result.frames[0].methods == ()


def test_timestamp_cap_is_enforced() -> None:
    boundary = load_default_boundary()
    observations = []
    for day in range(5):
        observations.extend(_frame_observations(6.8 + day, T0 + timedelta(days=day)))
    _store, sink = _sink()
    with pytest.raises(ResourceLimitError) as error:
        run_spatial_analysis(
            observations=observations,
            recipe=_recipe(),
            boundary=boundary,
            sink=sink,
            max_timestamps_per_run=3,
        )
    assert error.value.details["timestamps"] == 5


def test_grid_cell_cap_is_enforced() -> None:
    boundary = load_default_boundary()
    observations = _frame_observations(6.8, T0)
    _store, sink = _sink()
    with pytest.raises(ResourceLimitError) as error:
        run_spatial_analysis(
            observations=observations,
            recipe=_recipe(grid_resolution_m=100.0, max_grid_cells=1000),
            boundary=boundary,
            sink=sink,
        )
    assert "maximum cell count" in str(error.value)


def test_qc_excluded_and_failed_rows_are_not_used() -> None:
    import dataclasses

    boundary = load_default_boundary()
    rebuilt = []
    for i, obs in enumerate(_frame_observations(6.8, T0)):
        if i == 0:
            rebuilt.append(
                dataclasses.replace(obs, is_excluded=True, exclusion_reason="test exclusion")
            )
        elif i == 1:
            rebuilt.append(dataclasses.replace(obs, qc_status=QcStatus.FAIL))
        else:
            rebuilt.append(obs)
    _store, sink = _sink()
    result = run_spatial_analysis(
        observations=rebuilt, recipe=_recipe(), boundary=boundary, sink=sink
    )
    assert result.frames[0].point_count == 2
    assert result.frames[0].skipped_reason is not None


def test_recipe_requires_a_method_and_valid_rules() -> None:
    from trendsmapp.errors import ValidationError

    with pytest.raises(ValidationError):
        SpatialRecipe(methods=(), grid_resolution_m=1000.0, max_grid_cells=1000)
    with pytest.raises(ValidationError):
        _recipe(validation="bogus")
    with pytest.raises(ValidationError):
        _recipe(selection_rule="bogus")
