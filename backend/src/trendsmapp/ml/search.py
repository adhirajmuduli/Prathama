"""Reproducible bounded hyperparameter search on the configured inner split."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Sequence

import numpy as np

from trendsmapp.domain.enums import ModelFamily, SplitStrategy
from trendsmapp.errors import ValidationError
from trendsmapp.ml.metrics import regression_metrics
from trendsmapp.ml.models import ModelSpec, make_model
from trendsmapp.ml.splits import FrameTable, generate_splits

__all__ = ["DEFAULT_SEARCH_GRIDS", "SearchResult", "bounded_search"]

#: Default parameter grids per family; small on purpose — the budget bounds the work.
DEFAULT_SEARCH_GRIDS: Final[dict[ModelFamily, dict[str, list[Any]]]] = {
    ModelFamily.ELASTIC_NET: {"alpha": [0.01, 0.1, 1.0], "l1_ratio": [0.0, 0.5, 1.0]},
    ModelFamily.RANDOM_FOREST: {"n_estimators": [100, 300], "max_depth": [None, 8, 16]},
    ModelFamily.EXTRA_TREES: {"n_estimators": [100, 300], "max_depth": [None, 8, 16]},
    ModelFamily.HIST_GRADIENT_BOOSTING: {"max_iter": [100, 300], "learning_rate": [0.05, 0.1]},
    ModelFamily.XGBOOST: {"n_estimators": [100, 300], "max_depth": [4, 6], "learning_rate": [0.05, 0.1]},
}


@dataclass(frozen=True, slots=True)
class SearchResult:
    """The outcome of one bounded search."""

    family: ModelFamily
    best_params: dict[str, Any]
    best_score: float
    evaluations: int


def bounded_search(
    family: ModelFamily,
    x: np.ndarray,
    y: np.ndarray,
    groups: list[str],
    *,
    budget: int,
    seed: int,
    primary_metric: str,
    inner_strategy: SplitStrategy,
    years: list[int] | None = None,
    sectors: list[str] | None = None,
    coords_m: np.ndarray | None = None,
) -> SearchResult:
    """Search the family's grid within the budget on the inner split folds.

    Candidates are evaluated in deterministic grid order; the first ``budget``
    candidates run. The score is the mean primary metric over the inner folds.
    """
    grid = DEFAULT_SEARCH_GRIDS.get(family)
    if grid is None:
        # baselines have no hyperparameters
        return SearchResult(family=family, best_params={}, best_score=float("nan"), evaluations=0)

    keys = sorted(grid)
    combos: list[dict[str, Any]] = [dict()]
    for key in keys:
        combos = [dict(combo, **{key: value}) for combo in combos for value in grid[key]]
    if len(combos) > budget:
        combos = combos[:budget]

    if inner_strategy in {SplitStrategy.STATION_GROUP, SplitStrategy.LEAVE_YEAR_OUT, SplitStrategy.SECTOR, SplitStrategy.COMBINED, SplitStrategy.SPATIAL_BLOCK, SplitStrategy.ROLLING_ORIGIN}:
        if years is None or sectors is None or coords_m is None:
            raise ValidationError("Inner split needs years, sectors, and coords.")
        table = FrameTable(
            station_ids=groups,
            years=years,
            sectors=sectors,
            coords_m=coords_m,
            timestamps=[None] * len(groups),  # type: ignore[list-item]
        )
        folds = generate_splits(inner_strategy, table, seed=seed)
    else:
        folds = generate_splits(inner_strategy, _minimal_table(groups), seed=seed)

    best: SearchResult | None = None
    evaluations = 0
    for combo in combos:
        scores: list[float] = []
        for train_idx, test_idx in folds:
            model = make_model(ModelSpec(family=family, params=dict(combo), seed=seed))
            model.fit(x[train_idx], y[train_idx], [groups[i] for i in train_idx])
            predictions = model.predict(x[test_idx], [groups[i] for i in test_idx])
            scores.append(regression_metrics(y[test_idx], predictions)[primary_metric])
        score = float(np.mean(scores)) if scores else float("nan")
        evaluations += 1
        if best is None or score < best.best_score:
            best = SearchResult(family=family, best_params=dict(combo), best_score=score, evaluations=evaluations)
    if best is None:
        raise ValidationError("The search budget produced no candidates.")
    return best


def _minimal_table(groups: list[str]) -> FrameTable:
    """Build a minimal FrameTable for random-row inner splits."""
    n = len(groups)
    return FrameTable(
        station_ids=groups,
        years=[2024] * n,
        sectors=["s"] * n,
        coords_m=np.zeros((n, 2)),
        timestamps=[None] * n,  # type: ignore[list-item]
    )
