"""Functional estimator registry and adapters for each approved model family.

This module imports documented estimators from scikit-learn and XGBoost. It does
not copy, reimplement, or vendor any estimator source code. Each family is an
adapter with a uniform fit/predict interface, so the training loop never cares
which library produced the model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final, Protocol, cast

import numpy as np

from trendsmapp.domain.enums import ModelFamily
from trendsmapp.errors import ValidationError
from trendsmapp.ml.baselines import (
    MeanBaseline,
    SeasonalClimatology,
    StationClimatology,
)

__all__ = [
    "MODEL_REGISTRY",
    "ModelCapability",
    "ModelEntry",
    "ModelSpec",
    "TrainableModel",
    "capability_for",
    "make_model",
    "validate_models",
]


class TrainableModel(Protocol):
    """The uniform interface the training loop uses."""

    def fit(self, x: np.ndarray, y: np.ndarray, groups: list[str] | None = None) -> None: ...

    def predict(self, x: np.ndarray, groups: list[str] | None = None) -> np.ndarray: ...


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """One candidate model with its hyperparameters and seed."""

    family: ModelFamily
    params: dict[str, Any] = field(default_factory=dict)
    seed: int = 0


@dataclass(frozen=True, slots=True)
class ModelCapability:
    """What a model family supports."""

    family: ModelFamily
    #: Whether SHAP TreeExplainer can explain fitted instances of this family.
    supports_shap_tree: bool
    #: Whether the family needs the station id as a group input.
    needs_groups: bool
    description: str


@dataclass(frozen=True, slots=True)
class ModelEntry:
    """One registered model family."""

    family: ModelFamily
    capability: ModelCapability
    factory: Any


class _SklearnAdapter:
    """Adapt a scikit-learn-style estimator to the TrainableModel protocol."""

    def __init__(self, estimator: Any) -> None:
        self._estimator = estimator

    @property
    def estimator(self) -> Any:
        """Return the wrapped estimator.

        Explainers such as SHAP need the fitted estimator itself, not the
        adapter, so this accessor is part of the adapter's contract.
        """
        return self._estimator

    def fit(self, x: np.ndarray, y: np.ndarray, groups: list[str] | None = None) -> None:
        """Fit the estimator, ignoring groups."""
        self._estimator.fit(np.asarray(x, dtype=float), np.asarray(y, dtype=float))

    def predict(self, x: np.ndarray, groups: list[str] | None = None) -> np.ndarray:
        """Predict for the given feature rows."""
        return np.asarray(self._estimator.predict(np.asarray(x, dtype=float)), dtype=float)


def _sklearn_factory(cls: Any, seed: int, params: dict[str, Any]) -> Any:
    """Build a scikit-learn estimator with the seed injected where supported."""
    kwargs = dict(params)
    if "random_state" in cls().get_params():
        kwargs.setdefault("random_state", seed)
    return cls(**kwargs)


def _entry(
    family: ModelFamily,
    factory: Any,
    *,
    supports_shap_tree: bool,
    needs_groups: bool = False,
    description: str = "",
) -> ModelEntry:
    return ModelEntry(
        family=family,
        capability=ModelCapability(
            family=family,
            supports_shap_tree=supports_shap_tree,
            needs_groups=needs_groups,
            description=description,
        ),
        factory=factory,
    )


def _build_registry() -> dict[ModelFamily, ModelEntry]:
    """Build the registry, importing estimators lazily per family."""
    from sklearn.ensemble import (
        ExtraTreesRegressor,
        HistGradientBoostingRegressor,
        RandomForestRegressor,
    )
    from sklearn.linear_model import ElasticNet

    registry: dict[ModelFamily, ModelEntry] = {}
    registry[ModelFamily.MEAN_BASELINE] = _entry(
        ModelFamily.MEAN_BASELINE,
        lambda spec: MeanBaseline(),
        supports_shap_tree=False,
        description="Mean of the training target.",
    )
    registry[ModelFamily.STATION_CLIMATOLOGY] = _entry(
        ModelFamily.STATION_CLIMATOLOGY,
        lambda spec: StationClimatology(),
        supports_shap_tree=False,
        needs_groups=True,
        description="Per-station training mean; unseen stations fall back to the global mean.",
    )
    registry[ModelFamily.SEASONAL_CLIMATOLOGY] = _entry(
        ModelFamily.SEASONAL_CLIMATOLOGY,
        lambda spec: SeasonalClimatology(),
        supports_shap_tree=False,
        needs_groups=True,
        description="Per-station per-season training mean.",
    )
    registry[ModelFamily.ELASTIC_NET] = _entry(
        ModelFamily.ELASTIC_NET,
        # Coordinate descent needs headroom to converge on standardized
        # features; the default 1000 iterations warns on small folds.
        lambda spec: _SklearnAdapter(
            _sklearn_factory(ElasticNet, spec.seed, {"max_iter": 10_000, **spec.params})
        ),
        supports_shap_tree=False,
        description="scikit-learn ElasticNet.",
    )
    registry[ModelFamily.RANDOM_FOREST] = _entry(
        ModelFamily.RANDOM_FOREST,
        lambda spec: _SklearnAdapter(
            _sklearn_factory(RandomForestRegressor, spec.seed, spec.params)
        ),
        supports_shap_tree=True,
        description="scikit-learn RandomForestRegressor.",
    )
    registry[ModelFamily.EXTRA_TREES] = _entry(
        ModelFamily.EXTRA_TREES,
        lambda spec: _SklearnAdapter(_sklearn_factory(ExtraTreesRegressor, spec.seed, spec.params)),
        supports_shap_tree=True,
        description="scikit-learn ExtraTreesRegressor.",
    )
    registry[ModelFamily.HIST_GRADIENT_BOOSTING] = _entry(
        ModelFamily.HIST_GRADIENT_BOOSTING,
        lambda spec: _SklearnAdapter(
            _sklearn_factory(HistGradientBoostingRegressor, spec.seed, spec.params)
        ),
        supports_shap_tree=True,
        description="scikit-learn HistGradientBoostingRegressor.",
    )

    def _xgboost_factory(spec: ModelSpec) -> Any:
        from xgboost import XGBRegressor

        params = dict(spec.params)
        params.setdefault("random_state", spec.seed)
        params.setdefault("n_jobs", 1)  # CPU-only and deterministic in CI
        params.setdefault("tree_method", "hist")
        return _SklearnAdapter(XGBRegressor(**params))

    registry[ModelFamily.XGBOOST] = _entry(
        ModelFamily.XGBOOST,
        _xgboost_factory,
        supports_shap_tree=True,
        description="XGBoost XGBRegressor through its scikit-learn-compatible API.",
    )
    return registry


#: The registry of implemented model families.
MODEL_REGISTRY: Final[dict[ModelFamily, ModelEntry]] = _build_registry()


def capability_for(family: ModelFamily) -> ModelCapability:
    """Return the capability of a registered model family."""
    entry = MODEL_REGISTRY.get(family)
    if entry is None:
        raise ValidationError(
            f"The model family '{getattr(family, 'value', family)}' is not implemented.",
            details={"implemented": sorted(f.value for f in MODEL_REGISTRY)},
        )
    return entry.capability


def validate_models(families: list[ModelFamily]) -> None:
    """Validate that every family is registered and not configured twice."""
    seen: set[ModelFamily] = set()
    for family in families:
        capability_for(family)
        if family in seen:
            raise ValidationError(
                f"The model '{family.value}' is configured twice.",
                details={"family": family.value},
            )
        seen.add(family)


def make_model(spec: ModelSpec) -> TrainableModel:
    """Build one model instance from a spec via the registry."""
    entry = MODEL_REGISTRY.get(spec.family)
    if entry is None:
        raise ValidationError(
            f"The model family '{spec.family.value}' is not implemented.",
            details={"implemented": sorted(f.value for f in MODEL_REGISTRY)},
        )
    return cast(TrainableModel, entry.factory(spec))
