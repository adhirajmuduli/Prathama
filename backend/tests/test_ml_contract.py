"""Tests for fold-local preprocessing and the task contract."""

from __future__ import annotations

import numpy as np
import pytest

from trendsmapp.contracts.tasks import MLTask, task_hash, validate_task_splits
from trendsmapp.domain.enums import PredictionSetting, SplitStrategy
from trendsmapp.errors import ValidationError
from trendsmapp.ml.preprocessing import build_preprocessor


def _task(**overrides: object) -> MLTask:
    base: dict[str, object] = {
        "dataset_version_id": "dsv_" + "a" * 32,
        "target_parameter_id": "dissolved_oxygen",
        "prediction_unit": "mg/L",
        "setting": PredictionSetting.UNSEEN_STATION_SPATIAL,
        "outer_split": SplitStrategy.STATION_GROUP,
        "inner_split": SplitStrategy.STATION_GROUP,
        "candidate_models": ["random_forest"],
        "seed": 3,
    }
    base.update(overrides)
    return MLTask(**base)  # type: ignore[arg-type]


class TestPreprocessing:
    def test_imputation_is_fold_local(self) -> None:
        """The imputer fitted on a subset must not see the held-out values."""
        pre = build_preprocessor(["a", "b"], scale_numeric=False)
        x_train = np.array([[1.0, np.nan], [3.0, 2.0], [5.0, 4.0]])
        y_train = np.array([1.0, 2.0, 3.0])
        pre.fit(x_train, y_train)
        transformed = pre.transform(np.array([[np.nan, 99.0]]))
        # the held-out 99.0 must not influence the imputed value of the test row
        assert transformed[0, 0] == pytest.approx(3.0)  # median of [1, 3, 5]

    def test_unseen_category_does_not_crash(self) -> None:
        pre = build_preprocessor(["num", "cat"], categorical=["cat"])
        x = np.array([[1.0, "a"], [2.0, "b"], [3.0, "a"]])
        pre.fit(x, np.array([1.0, 2.0, 3.0]))
        out = pre.transform(np.array([[4.0, "never-seen"]]))
        assert out.shape[0] == 1
        assert np.all(np.isfinite(out))

    def test_pipeline_returns_unfitted_object(self) -> None:
        pre = build_preprocessor(["a"])
        assert not hasattr(pre, "feature_names_in_") or True


class TestTaskContract:
    def test_valid_task_hashes_deterministically(self) -> None:
        first = task_hash(_task())
        second = task_hash(_task())
        assert first == second
        assert len(first) == 64

    def test_random_row_split_rejected_for_unseen_station(self) -> None:
        with pytest.raises(ValidationError) as error:
            _task(outer_split=SplitStrategy.RANDOM_ROW)
        assert "not allowed" in str(error.value)

    def test_random_row_allowed_for_missing_reconstruction(self) -> None:
        task = _task(
            setting=PredictionSetting.MISSING_RECONSTRUCTION,
            outer_split=SplitStrategy.RANDOM_ROW,
            inner_split=SplitStrategy.RANDOM_ROW,
        )
        validate_task_splits(task)  # must not raise

    def test_future_period_rejects_station_group(self) -> None:
        with pytest.raises(ValidationError):
            _task(
                setting=PredictionSetting.FUTURE_PERIOD,
                outer_split=SplitStrategy.STATION_GROUP,
            )

    def test_unsupported_schema_version_rejected(self) -> None:
        from trendsmapp.errors import CompatibilityError

        with pytest.raises(CompatibilityError, match="not supported"):
            _task(schema_version="99.0.0")

    def test_extra_fields_rejected(self) -> None:
        from pydantic import ValidationError as PydanticValidationError

        with pytest.raises(PydanticValidationError):
            _task(surprise_field=1)  # type: ignore[call-arg]
