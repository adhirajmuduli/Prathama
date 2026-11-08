"""Tests for the ML pipeline, model artifacts, and uncertainty."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from trendsmapp.contracts.tasks import MLTask
from trendsmapp.domain.enums import (
    ModelFamily,
    PredictionSetting,
    QcStatus,
    SplitStrategy,
    UncertaintyMethod,
)
from trendsmapp.domain.models import Observation
from trendsmapp.errors import ResourceLimitError, ValidationError
from trendsmapp.ml.artifacts import load_model, save_model
from trendsmapp.ml.pipeline import build_feature_frame, run_ml_task
from trendsmapp.ml.uncertainty import compute_uncertainty

T0 = datetime(2024, 1, 15, 9, 30, tzinfo=UTC)


def _observation(
    index: int,
    *,
    station: str,
    day: int,
    value: float,
    parameter: str = "dissolved_oxygen",
    status: QcStatus = QcStatus.PASS,
    excluded: bool = False,
) -> Observation:
    from trendsmapp.domain.enums import ValueQualifier

    return Observation(
        observation_id=f"obs_{index:032d}",
        dataset_id="ds_test",
        dataset_version_id="dsv_test",
        source_row=index + 2,
        source_sheet=None,
        station_id=f"stn_{station}",
        station_label=station,
        latitude_wgs84=19.735 + 0.01 * (index % 4),
        longitude_wgs84=85.47 + 0.01 * (index % 4),
        x_projected_m=None,
        y_projected_m=None,
        source_crs="EPSG:4326",
        analysis_crs="EPSG:32644",
        sector=None,
        sampled_at=T0 + timedelta(days=day),
        sampling_depth_m=0.5,
        parameter_id=parameter,
        parameter_label=parameter,
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
        is_excluded=excluded,
        exclusion_reason="test" if excluded else None,
        provenance_ids=(),
    )


def _observations(count: int = 48) -> list[Observation]:
    """Build a frame with consecutive rows per station and daily steps."""
    rows: list[Observation] = []
    for index in range(count):
        station = f"st{index // 12}"
        day = index % 12
        rows.append(
            _observation(
                index,
                station=station,
                day=day,
                value=6.0 + 0.1 * day + 0.05 * (index % 4),
            )
        )
    return rows


def _task(**overrides: object) -> MLTask:
    base: dict[str, object] = {
        "dataset_version_id": "dsv_" + "a" * 32,
        "target_parameter_id": "dissolved_oxygen",
        "prediction_unit": "mg/L",
        "setting": PredictionSetting.UNSEEN_STATION_SPATIAL,
        "outer_split": SplitStrategy.STATION_GROUP,
        "inner_split": SplitStrategy.STATION_GROUP,
        "candidate_models": (ModelFamily.RANDOM_FOREST,),
        "search_budget": 2,
        "primary_metric": "rmse",
        "seed": 4,
        "lag_policy": "daily",
    }
    base.update(overrides)
    return MLTask(**base)  # type: ignore[arg-type]


class TestFeatureFrame:
    def test_features_and_lineage_are_complete(self) -> None:
        frame = build_feature_frame(_observations(), _task())
        assert frame.feature_names == (
            "lag_1d",
            "day_of_year",
            "month",
            "season",
            "x_m",
            "y_m",
        )
        assert set(frame.lineage) == set(frame.feature_names)
        assert "earlier" in frame.lineage["lag_1d"]
        assert frame.x.shape == (48, 6)
        assert frame.y.shape == (48,)
        assert len(frame.groups) == 48
        assert len(frame.sha256) == 64

    def test_lag_feature_is_the_previous_observation_of_the_same_station(self) -> None:
        frame = build_feature_frame(_observations(), _task())
        # rows are ordered by the observations list: station cycles every four rows
        first = frame.x[0]
        assert np.isnan(first[0])  # no earlier observation for the first row
        second = frame.x[1]
        assert second[0] == pytest.approx(frame.y[0])

    def test_lag_policy_none_removes_lag_features(self) -> None:
        frame = build_feature_frame(_observations(), _task(lag_policy="none"))
        assert "lag_1d" not in frame.feature_names
        assert frame.x.shape[1] == 5

    def test_other_parameters_and_failed_rows_are_excluded(self) -> None:
        rows = _observations()
        rows.append(_observation(100, station="st0", day=0, value=9.0, parameter="salinity"))
        rows.append(_observation(101, station="st0", day=0, value=9.0, status=QcStatus.FAIL))
        rows.append(_observation(102, station="st0", day=0, value=9.0, excluded=True))
        frame = build_feature_frame(rows, _task())
        assert frame.x.shape[0] == 48

    def test_eligible_date_range_is_applied(self) -> None:
        frame = build_feature_frame(_observations(), _task(eligible_start="2024-01-20T00:00:00"))
        assert frame.x.shape[0] < 48

    def test_too_few_rows_are_refused(self) -> None:
        with pytest.raises(ResourceLimitError):
            build_feature_frame(_observations(10), _task())

    def test_feature_table_hash_is_stable_and_data_sensitive(self) -> None:
        first = build_feature_frame(_observations(), _task())
        second = build_feature_frame(_observations(), _task())
        assert first.sha256 == second.sha256
        changed = list(_observations())
        changed[0] = _observation(0, station="st0", day=0, value=99.0)
        third = build_feature_frame(changed, _task())
        assert third.sha256 != first.sha256


class TestArtifacts:
    def test_model_package_round_trips(self) -> None:

        from trendsmapp.ml.models import ModelSpec, make_model

        model = make_model(ModelSpec(family=ModelFamily.MEAN_BASELINE))
        preprocessor = object()
        payload = save_model(model, preprocessor, ["x_m"], _task())
        loaded_model, loaded_preprocessor, metadata = load_model(payload)
        assert loaded_model is not None
        assert loaded_preprocessor is not None
        assert metadata["feature_names"] == ["x_m"]
        assert "scikit_learn" in metadata["environment"]
        assert metadata["payload_sha256"]

    def test_tampered_payload_is_rejected(self) -> None:
        from trendsmapp.ml.models import ModelSpec, make_model

        model = make_model(ModelSpec(family=ModelFamily.MEAN_BASELINE))
        payload = bytearray(save_model(model, object(), ["x_m"], _task()))
        payload[-1] = (payload[-1] + 1) % 256
        with pytest.raises(ValidationError) as error:
            load_model(bytes(payload))
        assert "digest" in str(error.value)

    def test_unsupported_package_schema_is_rejected(self) -> None:
        import json

        from trendsmapp.ml.models import ModelSpec, make_model

        model = make_model(ModelSpec(family=ModelFamily.MEAN_BASELINE))
        payload = save_model(model, object(), ["x_m"], _task())
        newline = payload.index(b"\n")
        metadata = json.loads(payload[:newline].decode())
        metadata["schema_version"] = "99.0.0"
        rebuilt = json.dumps(metadata, sort_keys=True).encode() + b"\n" + payload[newline + 1 :]
        with pytest.raises(ValidationError) as error:
            load_model(rebuilt)
        assert "schema version" in str(error.value)


class TestUncertainty:
    def test_bootstrap_ensemble_produces_ordered_intervals(self) -> None:
        rng = np.random.default_rng(0)
        x_train = rng.normal(size=(60, 2))
        y_train = 2.0 * x_train[:, 0] + rng.normal(scale=0.05, size=60)
        x_test = rng.normal(size=(20, 2))
        y_test = 2.0 * x_test[:, 0] + rng.normal(scale=0.05, size=20)

        def fit_predict(x_tr, y_tr, seed):
            from trendsmapp.ml.models import ModelSpec, make_model

            model = make_model(
                ModelSpec(family=ModelFamily.RANDOM_FOREST, params={"n_estimators": 10}, seed=seed)
            )
            model.fit(x_tr, y_tr)
            return lambda x_te: np.asarray(model.predict(x_te), dtype=float)

        result = compute_uncertainty(
            UncertaintyMethod.BOOTSTRAP_ENSEMBLE,
            fit_predict=fit_predict,
            x_train=x_train,
            y_train=y_train,
            x_test=x_test,
            y_test=y_test,
            seed=1,
        )
        assert result.lower.shape == (20,)
        assert np.all(result.lower <= result.upper)
        assert result.empirical_coverage is not None
        assert 0.0 <= result.empirical_coverage <= 1.0

    def test_quantile_uncertainty_produces_ordered_intervals(self) -> None:
        rng = np.random.default_rng(1)
        x_train = rng.normal(size=(80, 2))
        y_train = x_train[:, 0] + rng.normal(scale=0.05, size=80)
        x_test = rng.normal(size=(10, 2))

        def fit_predict(x_tr, y_tr, seed):
            return lambda x_te: (
                np.asarray(np.mean(y_tr), dtype=float) + 0.0 * np.asarray(x_te)[:, 0]
            )

        result = compute_uncertainty(
            UncertaintyMethod.QUANTILE,
            fit_predict=fit_predict,
            x_train=x_train,
            y_train=y_train,
            x_test=x_test,
            y_test=None,
            seed=2,
        )
        assert result.lower.shape == (10,)
        assert np.all(result.lower <= result.upper)
        assert result.empirical_coverage is None


class TestRunMlTask:
    def test_task_runs_and_stores_its_artifacts(self) -> None:
        stored: dict[str, bytes] = {}

        def sink(kind: str, name: str, payload: bytes, content_type: str, metadata: dict) -> str:
            key = f"{kind}/{name}"
            stored[key] = payload
            return key

        result = run_ml_task(_task(), _observations(), sink=sink)
        assert result.model_storage_key in stored
        assert result.results_storage_key in stored
        assert result.training.selected_family is ModelFamily.RANDOM_FOREST
        assert result.uncertainty.lower.shape[0] > 0
        assert result.training.aggregated["random_forest"]["folds"] == 4
        assert "mean_baseline" in result.training.baseline_comparison

    def test_run_is_deterministic(self) -> None:
        first = run_ml_task(_task(), _observations())
        second = run_ml_task(_task(), _observations())
        assert first.feature_frame.sha256 == second.feature_frame.sha256
        assert first.training.selected_params == second.training.selected_params
        assert first.model_sha256 == second.model_sha256
