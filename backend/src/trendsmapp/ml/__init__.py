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
from trendsmapp.ml.preprocessing import build_preprocessor
from trendsmapp.ml.splits import Fold, FrameTable, generate_splits

__all__ = [
    "MODEL_REGISTRY",
    "Fold",
    "FrameTable",
    "MeanBaseline",
    "MedianBaseline",
    "ModelCapability",
    "ModelEntry",
    "ModelSpec",
    "PersistenceBaseline",
    "SeasonalClimatology",
    "StationClimatology",
    "TrainableModel",
    "build_preprocessor",
    "capability_for",
    "generate_splits",
    "make_model",
    "validate_models",
]
