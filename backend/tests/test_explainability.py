"""Tests for the explainability layer."""

from __future__ import annotations

import numpy as np
import pytest

from trendsmapp.domain.enums import ExplanationMethod, ModelFamily
from trendsmapp.explainability.payloads import ExplanationTable, FeatureImportance
from trendsmapp.explainability.permutation import permutation_importance
from trendsmapp.explainability.pipeline import explain_model
from trendsmapp.explainability.shap_values import (
    MAX_SHAP_ROWS,
    shap_importance,
    supports_shap,
)
from trendsmapp.explainability.stability import importance_stability


def _linear_predictor(weights: np.ndarray):
    def predict(x: np.ndarray) -> np.ndarray:
        return np.asarray(x, dtype=float) @ weights

    return predict


class TestPermutationImportance:
    def test_useless_feature_has_no_importance(self) -> None:
        rng = np.random.default_rng(0)
        x = rng.normal(size=(200, 2))
        y = x[:, 0] * 2.0
        rows = permutation_importance(
            _linear_predictor(np.array([2.0, 0.0])),
            x,
            y,
            ("signal", "noise"),
            repeats=5,
            seed=1,
        )
        by_feature = {row["feature"]: row for row in rows}
        assert by_feature["signal"]["value"] > 0.5
        assert abs(by_feature["noise"]["value"]) < 0.05
        assert by_feature["signal"]["rank"] == 1

    def test_repeats_and_spread_are_recorded(self) -> None:
        rng = np.random.default_rng(1)
        x = rng.normal(size=(100, 1))
        y = x[:, 0]
        rows = permutation_importance(
            _linear_predictor(np.array([1.0])),
            x,
            y,
            ("signal",),
            repeats=4,
            seed=2,
        )
        assert rows[0]["detail"]["repeats"] == 4
        assert rows[0]["detail"]["std"] >= 0.0
        assert rows[0]["baseline"] == pytest.approx(0.0, abs=1e-6)

    def test_misaligned_inputs_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="align"):
            permutation_importance(
                _linear_predictor(np.array([1.0])),
                np.zeros((5, 1)),
                np.zeros(4),
                ("a",),
            )

    def test_unnamed_features_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="name"):
            permutation_importance(
                _linear_predictor(np.array([1.0])),
                np.zeros((5, 1)),
                np.zeros(5),
                (),
            )


class TestShap:
    def test_tree_families_are_supported(self) -> None:
        assert supports_shap(ModelFamily.RANDOM_FOREST) is True
        assert supports_shap(ModelFamily.XGBOOST) is True
        assert supports_shap(ModelFamily.MEAN_BASELINE) is False

    def test_shap_importance_is_bounded_and_additive(self) -> None:
        from sklearn.ensemble import RandomForestRegressor

        rng = np.random.default_rng(3)
        x = rng.normal(size=(120, 3))
        y = x[:, 0] * 3.0 + x[:, 1] + rng.normal(scale=0.05, size=120)
        model = RandomForestRegressor(n_estimators=20, random_state=0)
        model.fit(x, y)
        result = shap_importance(model, x, ("a", "b", "c"), seed=5)
        rows = result["rows"]
        assert len(rows) == 3
        assert rows[0]["rank"] == 1
        assert rows[0]["value"] > 0
        assert result["additivity_max_error"] < 1e-3
        assert rows[0]["detail"]["explained_rows"] == 120

    def test_explained_rows_are_capped(self) -> None:
        from sklearn.ensemble import RandomForestRegressor

        rng = np.random.default_rng(4)
        x = rng.normal(size=(MAX_SHAP_ROWS + 50, 2))
        y = x[:, 0]
        model = RandomForestRegressor(n_estimators=5, random_state=0)
        model.fit(x, y)
        result = shap_importance(model, x, ("a", "b"), max_rows=100, seed=0)
        assert result["rows"][0]["detail"]["explained_rows"] == 100


class TestStability:
    def test_identical_rankings_are_fully_stable(self) -> None:
        rows = importance_stability(
            {
                "fold1": {"a": 3.0, "b": 2.0, "c": 1.0},
                "fold2": {"a": 2.9, "b": 2.1, "c": 0.9},
            }
        )
        by_feature = {row["feature"]: row for row in rows}
        assert by_feature["a"]["value"] == pytest.approx(1.0)
        assert by_feature["a"]["detail"]["rank_min"] == 1
        assert by_feature["a"]["detail"]["groups"] == 2
        assert by_feature["a"]["detail"]["direction_agreement"] == pytest.approx(1.0)

    def test_reversed_rankings_are_unstable(self) -> None:
        rows = importance_stability(
            {
                "fold1": {"a": 3.0, "b": 2.0},
                "fold2": {"a": 1.0, "b": 4.0},
            }
        )
        by_feature = {row["feature"]: row for row in rows}
        assert by_feature["a"]["value"] == pytest.approx(0.0)
        assert by_feature["a"]["detail"]["rank_min"] == 1
        assert by_feature["a"]["detail"]["rank_max"] == 2

    def test_direction_disagreement_is_reported(self) -> None:
        rows = importance_stability(
            {
                "fold1": {"a": 3.0, "b": 2.0},
                "fold2": {"a": -1.0, "b": 2.0},
            }
        )
        by_feature = {row["feature"]: row for row in rows}
        assert by_feature["a"]["detail"]["direction_agreement"] == pytest.approx(0.5)
        assert by_feature["b"]["detail"]["direction_agreement"] == pytest.approx(1.0)

    def test_one_group_has_no_stability(self) -> None:
        assert importance_stability({"fold1": {"a": 1.0}}) == []


class TestExplainModel:
    def test_permutation_is_computed_and_unsupported_shap_is_recorded(self) -> None:
        from sklearn.ensemble import RandomForestRegressor

        rng = np.random.default_rng(7)
        x = rng.normal(size=(120, 2))
        y = x[:, 0] * 2.0
        estimator = RandomForestRegressor(n_estimators=10, random_state=0)
        estimator.fit(x, y)
        table = explain_model(
            family=ModelFamily.MEAN_BASELINE,
            predict=_linear_predictor(np.array([2.0, 0.0])),
            estimator=estimator,
            x=x,
            y=y,
            feature_names=("signal", "noise"),
            methods=(ExplanationMethod.PERMUTATION, ExplanationMethod.SHAP_TREE),
            seed=1,
        )
        assert isinstance(table, ExplanationTable)
        methods = {row.method for row in table.rows}
        assert "permutation" in methods
        assert any("shap_tree is not supported" in item for item in table.limitations)

    def test_shap_rows_are_added_for_tree_models(self) -> None:
        from sklearn.ensemble import RandomForestRegressor

        rng = np.random.default_rng(8)
        x = rng.normal(size=(100, 2))
        y = x[:, 0] * 2.0
        model = RandomForestRegressor(n_estimators=10, random_state=0)
        model.fit(x, y)
        table = explain_model(
            family=ModelFamily.RANDOM_FOREST,
            predict=lambda values: np.asarray(model.predict(values), dtype=float),
            estimator=model,
            x=x,
            y=y,
            feature_names=("a", "b"),
            methods=(ExplanationMethod.SHAP_TREE,),
            seed=2,
        )
        methods = {row.method for row in table.rows}
        assert "shap" in methods
        assert table.limitations == ()

    def test_stability_is_computed_when_groups_are_given(self) -> None:
        rng = np.random.default_rng(9)
        x = rng.normal(size=(120, 2))
        y = x[:, 0] * 2.0
        groups = [f"g{index % 3}" for index in range(120)]
        table = explain_model(
            family=ModelFamily.MEAN_BASELINE,
            predict=_linear_predictor(np.array([2.0, 0.0])),
            x=x,
            y=y,
            feature_names=("signal", "noise"),
            methods=(ExplanationMethod.PERMUTATION,),
            groups=groups,
            seed=3,
        )
        methods = {row.method for row in table.rows}
        assert "permutation" in methods
        assert "stability" in methods

    def test_payload_is_json_ready(self) -> None:
        row = FeatureImportance(feature="a", method="permutation", value=1.0, baseline=0.5, rank=1)
        table = ExplanationTable(
            model_family="mean_baseline",
            method="permutation",
            rows=(row,),
            limitations=("none",),
        )
        payload = table.as_payload()
        assert payload["rows"][0]["feature"] == "a"
        assert payload["limitations"] == ["none"]
