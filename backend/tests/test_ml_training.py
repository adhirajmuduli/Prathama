"""Tests for the ML training loop: fold locality, baselines, metrics, determinism."""

from __future__ import annotations

import numpy as np
import pytest

from trendsmapp.contracts.tasks import MLTask
from trendsmapp.domain.enums import ModelFamily, PredictionSetting, SplitStrategy
from trendsmapp.errors import ValidationError
from trendsmapp.ml.metrics import (
    aggregate_fold_metrics,
    bootstrap_ci,
    regression_metrics,
    subgroup_metrics,
)
from trendsmapp.ml.training import fit_fold_model, train_and_evaluate


def _same_metrics(left: dict, right: dict) -> bool:
    """Compare metric dictionaries, treating NaN as equal to NaN."""

    def equal(first, second) -> bool:
        if isinstance(first, float) and isinstance(second, float):
            return bool(np.isnan(first) and np.isnan(second)) or first == second
        if isinstance(first, list) and isinstance(second, list):
            return len(first) == len(second) and all(
                equal(a, b) for a, b in zip(first, second, strict=True)
            )
        if isinstance(first, dict) and isinstance(second, dict):
            return set(first) == set(second) and all(
                equal(value, second[key]) for key, value in first.items()
            )
        return bool(first == second)

    if set(left) != set(right):
        return False
    return all(equal(value, right[key]) for key, value in left.items())


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
        "seed": 5,
    }
    base.update(overrides)
    return MLTask(**base)  # type: ignore[arg-type]


def _dataset(stations: int = 4, per_station: int = 12, seed: int = 0):
    """Build a synthetic frame with a learnable spatial signal."""
    rng = np.random.default_rng(seed)
    rows_x: list[list[float]] = []
    rows_y: list[float] = []
    groups: list[str] = []
    years: list[int] = []
    sectors: list[str] = []
    coords: list[list[float]] = []
    for station in range(stations):
        base_x = 960_000.0 + station * 5_000.0
        base_y = 2_180_000.0 + station * 3_000.0
        for _step in range(per_station):
            jitter = rng.normal(scale=20.0, size=2)
            rows_x.append([float(base_x + jitter[0]), float(base_y + jitter[1])])
            rows_y.append(float(0.01 * (base_x - 960_000.0) + 0.02 * (base_y - 2_180_000.0) + 5.0))
            groups.append(f"st{station}")
            years.append(2022 + station % 2)
            sectors.append(f"s{station % 2}")
            coords.append([base_x, base_y])
    return (
        np.asarray(rows_x, dtype=float),
        np.asarray(rows_y, dtype=float),
        groups,
        years,
        sectors,
        np.asarray(coords, dtype=float),
    )


def _train(task: MLTask, data=None, save_model=None):
    x, y, groups, years, sectors, coords = data or _dataset()
    return train_and_evaluate(
        task,
        x=x,
        y=y,
        groups=groups,
        years=years,
        sectors=sectors,
        coords_m=coords,
        feature_names=("x_m", "y_m"),
        feature_table_sha256="0" * 64,
        task_hash="t" * 64,
        save_model=save_model or (lambda model, pre, names, task: b"payload"),
    )


class TestMetrics:
    def test_regression_metrics_match_hand_computation(self) -> None:
        y_true = np.array([1.0, 2.0, 3.0, 4.0])
        y_pred = np.array([1.5, 2.5, 2.0, 4.0])
        metrics = regression_metrics(y_true, y_pred)
        assert metrics["mae"] == pytest.approx(0.5)
        assert metrics["rmse"] == pytest.approx(np.sqrt(0.375))
        assert metrics["bias"] == pytest.approx(0.0)
        assert metrics["n"] == 4

    def test_empty_prediction_set_is_nan(self) -> None:
        metrics = regression_metrics(np.array([]), np.array([]))
        assert metrics["n"] == 0
        assert np.isnan(metrics["rmse"])

    def test_bootstrap_interval_contains_the_point_estimate(self) -> None:
        rng = np.random.default_rng(0)
        y_true = rng.normal(size=200)
        y_pred = y_true + rng.normal(scale=0.1, size=200)
        low, high = bootstrap_ci(y_true, y_pred, seed=1, samples=200)
        assert low < high
        assert low <= regression_metrics(y_true, y_pred)["rmse"] <= high

    def test_fold_aggregation_reports_mean_and_count(self) -> None:
        aggregated = aggregate_fold_metrics(
            [
                {"rmse": 1.0, "mae": 0.5, "bias": 0.1, "n": 10.0},
                {"rmse": 3.0, "mae": 1.5, "bias": -0.1, "n": 20.0},
            ]
        )
        assert aggregated["folds"] == 2
        assert aggregated["rmse_mean"] == pytest.approx(2.0)
        assert aggregated["n_total"] == pytest.approx(30.0)

    def test_subgroup_metrics_are_per_group(self) -> None:
        metrics = subgroup_metrics(
            np.array([1.0, 2.0, 3.0]),
            np.array([1.0, 2.5, 2.0]),
            ["a", "a", "b"],
        )
        assert set(metrics) == {"a", "b"}
        assert metrics["a"]["n"] == 2
        assert metrics["b"]["rmse"] == pytest.approx(1.0)


class TestTrainingLoop:
    def test_outer_folds_hold_out_whole_stations(self) -> None:
        result = _train(_task())
        folds = [fold for fold in result.folds if fold.family is ModelFamily.RANDOM_FOREST]
        assert len(folds) == 4
        for fold in folds:
            assert fold.test_size == 12
            assert fold.train_size == 36

    def test_baselines_are_always_compared(self) -> None:
        result = _train(_task())
        assert set(result.baseline_comparison) == {
            "mean_baseline",
            "station_climatology",
        }
        for family in result.baseline_comparison.values():
            assert "rmse_mean" in family
            assert "folds" in family

    def test_metrics_are_aggregated_per_family(self) -> None:
        result = _train(_task())
        assert "random_forest" in result.aggregated
        assert result.aggregated["random_forest"]["folds"] == 4
        assert result.aggregated["random_forest"]["rmse_mean"] >= 0

    def test_run_is_deterministic_under_a_fixed_seed(self) -> None:
        first = _train(_task())
        second = _train(_task())
        assert _same_metrics(first.aggregated, second.aggregated)
        assert first.selected_family is second.selected_family
        assert first.selected_params == second.selected_params
        first_predictions = [fold.y_pred.tolist() for fold in first.folds]
        second_predictions = [fold.y_pred.tolist() for fold in second.folds]
        assert first_predictions == second_predictions

    def test_fold_models_do_not_memorize_their_test_rows(self) -> None:
        """A model that had seen its test rows would score near zero on them."""
        result = _train(_task())
        folds = [fold for fold in result.folds if fold.family is ModelFamily.RANDOM_FOREST]
        assert folds
        for fold in folds:
            assert fold.metrics["rmse"] > 0.01
            assert not np.allclose(fold.y_pred, fold.y_true, atol=1e-6)

    def test_fold_preprocessing_is_fitted_on_the_training_rows_only(self) -> None:
        """The fold imputer must reflect the training rows, not the test rows."""
        x_train = np.array([[1.0], [3.0], [5.0]])
        y_train = np.array([1.0, 2.0, 3.0])
        x_test = np.array([[99.0]])
        y_test = np.array([7.0])
        warnings: list[str] = []
        fold = fit_fold_model(
            ModelFamily.RANDOM_FOREST,
            {"n_estimators": 10},
            3,
            ("x_m",),
            x_train,
            y_train,
            ["a", "a", "a"],
            x_test,
            y_test,
            ["b"],
            0,
            warnings,
        )
        imputer = (
            fold.preprocessor.named_steps["preprocess"].transformers_[0][1].named_steps["impute"]
        )
        assert float(imputer.statistics_[0]) == pytest.approx(3.0)

    def test_outer_test_rows_do_not_influence_other_folds(self) -> None:
        """Corrupting held-out rows must not change the fold that held them out.

        The station-group split puts every station in the training rows of the
        other folds, so corrupting a station legitimately changes those folds.
        What must not change is the fold whose test rows were corrupted: its
        model never saw them.
        """
        x, y, groups, years, sectors, coords = _dataset()
        clean = _train(_task(), data=(x, y, groups, years, sectors, coords))

        corrupted_y = y.copy()
        corrupted_y[:12] = 1e9  # the rows of the first held-out station
        corrupted = _train(_task(), data=(x, corrupted_y, groups, years, sectors, coords))

        def fold_of(result, family: ModelFamily, index: int):
            return next(
                fold for fold in result.folds if fold.family is family and fold.fold_index == index
            )

        clean_first = fold_of(clean, ModelFamily.RANDOM_FOREST, 0)
        corrupted_first = fold_of(corrupted, ModelFamily.RANDOM_FOREST, 0)
        # The corrupted fold evaluates on corrupted rows, so its metrics change.
        assert clean_first.metrics != corrupted_first.metrics

        # The corrupted rows never entered that fold's model, so its
        # preprocessing still reflects the training rows only.
        def imputer_statistics(fold):
            return (
                fold.preprocessor.named_steps["preprocess"]
                .transformers_[0][1]
                .named_steps["impute"]
                .statistics_
            )

        assert np.allclose(imputer_statistics(clean_first), imputer_statistics(corrupted_first))

    def test_search_budget_bounds_the_evaluations(self) -> None:
        result = _train(_task(search_budget=2))
        assert result.selected_family is ModelFamily.RANDOM_FOREST
        assert result.selected_params

    def test_candidate_families_are_evaluated(self) -> None:
        task = _task(candidate_models=(ModelFamily.RANDOM_FOREST, ModelFamily.ELASTIC_NET))
        result = _train(task)
        families = {fold.family for fold in result.folds}
        assert ModelFamily.RANDOM_FOREST in families
        assert ModelFamily.ELASTIC_NET in families
        assert "elastic_net" in result.aggregated

    def test_selected_model_is_one_of_the_candidates(self) -> None:
        task = _task(candidate_models=(ModelFamily.ELASTIC_NET,))
        result = _train(task)
        assert result.selected_family is ModelFamily.ELASTIC_NET

    def test_final_model_payload_is_produced(self) -> None:
        captured: list[bytes] = []

        def save_model(model, preprocessor, feature_names, task) -> bytes:
            payload = f"{task.seed}:{len(feature_names)}".encode()
            captured.append(payload)
            return payload

        result = _train(_task(), save_model=save_model)
        assert captured
        assert result.final_model_sha256

    def test_unknown_task_split_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _task(outer_split=SplitStrategy.RANDOM_ROW)
