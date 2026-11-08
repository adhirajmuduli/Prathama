"""Public ML exports."""

from __future__ import annotations

from trendsmapp.ml.baselines import (
    MeanBaseline,
    MedianBaseline,
    PersistenceBaseline,
    SeasonalClimatology,
    StationClimatology,
)
from trendsmapp.ml.models import (
    MODEL_REGISTRY,
    ModelCapability,
    ModelEntry,
    ModelSpec,
    TrainableModel,
    capability_for,
    make_model,
    validate_models,
)
from trendsmapp.ml.pipeline import (
    LAG_POLICIES,
    MIN_FRAME_ROWS,
    FeatureFrame,
    MLRunResult,
    build_feature_frame,
    run_ml_task,
)
from trendsmapp.ml.preprocessing import build_preprocessor
from trendsmapp.ml.splits import Fold, FrameTable, generate_splits

__all__ = [
    "LAG_POLICIES",
    "MIN_FRAME_ROWS",
    "MODEL_REGISTRY",
    "FeatureFrame",
    "Fold",
    "FrameTable",
    "MLRunResult",
    "MeanBaseline",
    "MedianBaseline",
    "ModelCapability",
    "ModelEntry",
    "ModelSpec",
    "PersistenceBaseline",
    "SeasonalClimatology",
    "StationClimatology",
    "TrainableModel",
    "build_feature_frame",
    "build_preprocessor",
    "capability_for",
    "generate_splits",
    "make_model",
    "run_ml_task",
    "validate_models",
]
