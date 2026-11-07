"""The versioned machine-learning task contract.

A model task is the request document of one ML run, analogous to the analysis
recipe. It is versioned, forbids extra fields, and its canonical JSON hash is
recorded on the run, so a model result can always be traced to the exact task
that produced it.
"""

from __future__ import annotations

import hashlib
import json
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, model_validator

from trendsmapp.contracts.versions import RECIPE_SCHEMA_VERSION, ensure_supported_recipe_schema
from trendsmapp.domain.enums import (
    SETTING_SPLIT_FAMILIES,
    ExplanationMethod,
    ModelFamily,
    PredictionSetting,
    SplitStrategy,
    UncertaintyMethod,
)
from trendsmapp.errors import ValidationError

__all__ = ["TASK_SCHEMA_VERSION", "MLTask", "task_hash", "validate_task_splits"]

#: The task schema version this build speaks (same line as the recipe schema).
TASK_SCHEMA_VERSION: Final[str] = RECIPE_SCHEMA_VERSION


class MLTask(BaseModel):
    """One machine-learning task.

    Every field the plan requires a run to declare is here: target, unit,
    prediction setting, eligible data, features, policies, evaluation, models,
    search budget, metric, seed, uncertainty, and explanations.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = TASK_SCHEMA_VERSION
    dataset_version_id: str = Field(min_length=1)
    target_parameter_id: str = Field(min_length=1)
    prediction_unit: str = Field(min_length=1)
    setting: PredictionSetting
    eligible_start: str | None = None
    eligible_end: str | None = None
    eligible_station_ids: tuple[str, ...] = ()
    feature_names: tuple[str, ...] = ()
    lag_policy: str = "none"
    missing_data_policy: str = "drop"
    qc_policy: str = "exclude_failed"
    outer_split: SplitStrategy = SplitStrategy.STATION_GROUP
    inner_split: SplitStrategy = SplitStrategy.STATION_GROUP
    candidate_models: tuple[ModelFamily, ...] = Field(min_length=1)
    search_budget: int = Field(default=20, ge=1, le=10_000)
    primary_metric: str = "rmse"
    seed: int = Field(default=0, ge=0)
    uncertainty_method: UncertaintyMethod = UncertaintyMethod.BOOTSTRAP_ENSEMBLE
    explanation_methods: tuple[ExplanationMethod, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> MLTask:
        """Reject unsupported schema versions and incompatible split/setting pairs."""
        ensure_supported_recipe_schema(self.schema_version)
        validate_task_splits(self)
        return self

    def canonical_json(self) -> str:
        """Return the deterministic canonical JSON of the task."""
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def validate_task_splits(task: MLTask) -> None:
    """Reject split strategies that are scientifically incompatible with the setting.

    Random row splitting is only allowed for missing-observation reconstruction;
    an unseen-station claim must hold out whole stations or spatial blocks.
    """
    allowed = SETTING_SPLIT_FAMILIES[task.setting]
    for strategy in (task.outer_split, task.inner_split):
        if strategy not in allowed:
            raise ValidationError(
                f"Split '{strategy.value}' is not allowed for setting "
                f"'{task.setting.value}'; allowed: {sorted(s.value for s in allowed)}.",
                details={
                    "setting": task.setting.value,
                    "split": strategy.value,
                    "allowed": sorted(s.value for s in allowed),
                },
            )


def task_hash(task: MLTask) -> str:
    """Return the SHA-256 of the task's canonical JSON."""
    return hashlib.sha256(task.canonical_json().encode("utf-8")).hexdigest()
