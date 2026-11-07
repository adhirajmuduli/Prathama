"""Tests for the model registry, adapters, and baselines."""

from __future__ import annotations

import numpy as np
import pytest

from trendsmapp.domain.enums import ModelFamily
from trendsmapp.errors import ValidationError
from trendsmapp.ml.baselines import (
    MeanBaseline,
    MedianBaseline,
    PersistenceBaseline,
    SeasonalClimatology,
    StationClimatology,
)
from trendsmapp.ml.models import (
    MODEL_REGISTRY,
    ModelSpec,
    capability_for,
    make_model,
    validate_models,
)


def _toy_data(n: int = 40, seed: int = 0) -> tuple[np.ndarray, np.ndarray, list[str]]:
    rng = np.random.default_rng(seed)
    x = rng.normal(size=(n, 3))
    y = 2.0 * x[:, 0] - x[:, 1] + rng.normal(scale=0.01, size=n)
    groups = [f"st{i % 4}" for i in range(n)]
    return x, y, groups


class TestRegistry:
    def test_all_approved_families_registered(self) -> None:
        assert set(MODEL_REGISTRY) == {
            ModelFamily.MEAN_BASELINE,
            ModelFamily.STATION_CLIMATOLOGY,
            ModelFamily.SEASONAL_CLIMATOLOGY,
            ModelFamily.ELASTIC_NET,
            ModelFamily.RANDOM_FOREST,
            ModelFamily.EXTRA_TREES,
            ModelFamily.HIST_GRADIENT_BOOSTING,
            ModelFamily.XGBOOST,
        }
        for family in MODEL_REGISTRY:
            assert capability_for(family).family is family

    def test_unknown_family_rejected(self) -> None:
        with pytest.raises(ValidationError):
            validate_models(["not_a_model"])  # type: ignore[list-item]

    def test_duplicate_families_rejected(self) -> None:
        with pytest.raises(ValidationError):
            validate_models([ModelFamily.RANDOM_FOREST, ModelFamily.RANDOM_FOREST])

    def test_shap_capability_flags(self) -> None:
        assert capability_for(ModelFamily.RANDOM_FOREST).supports_shap_tree is True
        assert capability_for(ModelFamily.MEAN_BASELINE).supports_shap_tree is False


class TestAdapters:
    @pytest.mark.parametrize(
        "family",
        [
            ModelFamily.ELASTIC_NET,
            ModelFamily.RANDOM_FOREST,
            ModelFamily.EXTRA_TREES,
            ModelFamily.HIST_GRADIENT_BOOSTING,
            ModelFamily.XGBOOST,
        ],
    )
    def test_sklearn_families_fit_and_predict(self, family: ModelFamily) -> None:
        x, y, groups = _toy_data()
        model = make_model(
            ModelSpec(
                family=family,
                params={"n_estimators": 10, "max_depth": 4}
                if family in {ModelFamily.RANDOM_FOREST, ModelFamily.EXTRA_TREES}
                else {"max_iter": 200},
                seed=3,
            )
        )
        model.fit(x, y, groups)
        predictions = model.predict(x, groups)
        assert predictions.shape == y.shape
        assert np.all(np.isfinite(predictions))

    def test_determinism_under_seed(self) -> None:
        x, y, groups = _toy_data()
        first = make_model(ModelSpec(family=ModelFamily.RANDOM_FOREST, seed=11))
        second = make_model(ModelSpec(family=ModelFamily.RANDOM_FOREST, seed=11))
        first.fit(x, y, groups)
        second.fit(x, y, groups)
        np.testing.assert_array_equal(first.predict(x), second.predict(x))


class TestBaselines:
    def test_mean_and_median(self) -> None:
        x, y, groups = _toy_data()
        mean = MeanBaseline()
        mean.fit(x, y, groups)
        np.testing.assert_allclose(mean.predict(x), np.mean(y))
        median = MedianBaseline()
        median.fit(x, y, groups)
        np.testing.assert_allclose(median.predict(x), np.median(y))

    def test_station_climatology_uses_training_groups(self) -> None:
        x = np.zeros((4, 1))
        y = np.array([1.0, 3.0, 10.0, 20.0])
        groups = ["a", "a", "b", "b"]
        model = StationClimatology()
        model.fit(x, y, groups)
        predictions = model.predict(x, groups)
        np.testing.assert_allclose(predictions, [2.0, 2.0, 15.0, 15.0])
        # an unseen station falls back to the global mean
        unseen = model.predict(x, ["c", "c", "a", "b"])
        np.testing.assert_allclose(unseen, [np.mean(y)] * 2 + [2.0, 15.0])

    def test_seasonal_climatology(self) -> None:
        x = np.array([[0, 0], [0, 0], [0, 1], [0, 1]])
        y = np.array([1.0, 3.0, 10.0, 20.0])
        groups = ["a", "a", "a", "a"]
        model = SeasonalClimatology()
        model.fit(x, y, groups)
        predictions = model.predict(x, groups)
        np.testing.assert_allclose(predictions, [2.0, 2.0, 15.0, 15.0])

    def test_persistence_echoes_first_column(self) -> None:
        x, y, groups = _toy_data()
        model = PersistenceBaseline()
        model.fit(x, y, groups)
        np.testing.assert_allclose(model.predict(x), x[:, 0])
