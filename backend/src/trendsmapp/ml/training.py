"""Outer evaluation, inner tuning, fold artifacts, final refit, seed control.

The loop never lets an outer test row influence preprocessing or tuning: per
outer fold, preprocessing is fit on the outer-train rows only, inner search runs
on inner folds of the outer-train rows, and the fold model is evaluated on the
untouched outer test rows. The final model is refit on all data only after every
fold has been evaluated.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Final

import numpy as np

from trendsmapp.contracts.tasks import MLTask
from trendsmapp.domain.enums import ModelFamily
from trendsmapp.ml.metrics import aggregate_fold_metrics, bootstrap_ci, regression_metrics
from trendsmapp.ml.models import ModelSpec, make_model
from trendsmapp.ml.preprocessing import build_preprocessor
from trendsmapp.ml.search import bounded_search
from trendsmapp.ml.splits import Fold, FrameTable, generate_splits

__all__ = ["FoldResult", "TrainingResult", "fit_fold_model", "train_and_evaluate"]

#: Baselines every ML model is compared against.
BASELINE_FAMILIES: Final[tuple[ModelFamily, ...]] = (
    ModelFamily.MEAN_BASELINE,
    ModelFamily.STATION_CLIMATOLOGY,
)


@dataclass(frozen=True, slots=True)
class FoldResult:
    """One outer fold's outcome for one model.

    ``preprocessor`` is kept so a reviewer can verify that imputation and
    encoding were fitted on the fold's training rows only, and ``test_index``
    points at the held-out rows so explanations can be computed on data the
    model never saw.
    """

    fold_index: int
    family: ModelFamily
    train_size: int
    test_size: int
    metrics: dict[str, float]
    y_true: np.ndarray
    y_pred: np.ndarray
    warnings: tuple[str, ...]
    preprocessor: Any = None
    test_index: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class TrainingResult:
    """The aggregated outcome of one training run."""

    task_hash: str
    feature_names: tuple[str, ...]
    feature_table_sha256: str
    folds: tuple[FoldResult, ...]
    aggregated: dict[str, dict[str, Any]]
    baseline_comparison: dict[str, dict[str, Any]]
    selected_family: ModelFamily
    selected_params: dict[str, Any]
    final_model_sha256: str
    warnings: tuple[str, ...]
    #: The final refit model and its preprocessor, for explanations.
    final_model: Any = None
    final_preprocessor: Any = None


@dataclass(frozen=True, slots=True)
class _FoldData:
    """One outer fold's train/test split, pre-indexed for evaluation."""

    x_train: np.ndarray
    y_train: np.ndarray
    x_test: np.ndarray
    y_test: np.ndarray
    groups_train: list[str]
    groups_test: list[str]
    years_train: list[int]
    sectors_train: list[str]
    coords_train: np.ndarray
    train_size: int
    test_size: int
    test_index: tuple[int, ...]


def _evaluate_candidate(
    family: ModelFamily,
    fold: _FoldData,
    fold_index: int,
    task: MLTask,
    feature_names: Sequence[str],
    warnings: list[str],
) -> FoldResult:
    """Search and fit one candidate model on one outer fold."""
    best = bounded_search(
        family,
        fold.x_train,
        fold.y_train,
        fold.groups_train,
        budget=task.search_budget,
        seed=task.seed,
        primary_metric=task.primary_metric,
        inner_strategy=task.inner_split,
        years=fold.years_train,
        sectors=fold.sectors_train,
        coords_m=fold.coords_train,
    )
    result = fit_fold_model(
        family,
        best.best_params,
        task.seed,
        feature_names,
        fold.x_train,
        fold.y_train,
        fold.groups_train,
        fold.x_test,
        fold.y_test,
        fold.groups_test,
        fold_index,
        warnings,
    )
    return FoldResult(
        fold_index=fold_index,
        family=family,
        train_size=fold.train_size,
        test_size=fold.test_size,
        metrics=result.metrics,
        y_true=result.y_true,
        y_pred=result.y_pred,
        warnings=result.warnings,
        preprocessor=result.preprocessor,
        test_index=fold.test_index,
    )


def _evaluate_baseline(
    family: ModelFamily, fold: _FoldData, fold_index: int, task: MLTask
) -> FoldResult:
    """Fit one baseline on one outer fold (no hyperparameter search)."""
    model = make_model(ModelSpec(family=family, seed=task.seed))
    model.fit(fold.x_train, fold.y_train, fold.groups_train)
    y_pred = np.asarray(model.predict(fold.x_test, fold.groups_test), dtype=float)
    return FoldResult(
        fold_index=fold_index,
        family=family,
        train_size=fold.train_size,
        test_size=fold.test_size,
        metrics=regression_metrics(fold.y_test, y_pred),
        y_true=fold.y_test,
        y_pred=y_pred,
        warnings=(),
    )


def _aggregate_folds(
    fold_results: dict[ModelFamily, list[FoldResult]],
    all_families: list[ModelFamily],
    task: MLTask,
) -> dict[str, dict[str, Any]]:
    """Aggregate per-fold metrics per family, with bootstrap CIs on the primary metric."""
    aggregated: dict[str, dict[str, Any]] = {}
    for family in all_families:
        folds = fold_results[family]
        aggregated[family.value] = aggregate_fold_metrics([fold.metrics for fold in folds])
        if folds:
            all_true = np.concatenate([fold.y_true for fold in folds])
            all_pred = np.concatenate([fold.y_pred for fold in folds])
            low, high = bootstrap_ci(all_true, all_pred, seed=task.seed, metric=task.primary_metric)
            aggregated[family.value][f"{task.primary_metric}_ci95"] = [low, high]
    return aggregated


def train_and_evaluate(
    task: MLTask,
    *,
    x: np.ndarray,
    y: np.ndarray,
    groups: list[str],
    years: list[int],
    sectors: list[str],
    coords_m: np.ndarray,
    feature_names: Sequence[str],
    feature_table_sha256: str,
    task_hash: str,
    save_model: Callable[..., bytes],
) -> TrainingResult:
    """Run the full outer/inner evaluation for every candidate and baseline."""
    n = len(y)
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    table = FrameTable(
        station_ids=groups,
        years=years,
        sectors=sectors,
        coords_m=coords_m,
        timestamps=[None] * n,
    )
    outer_folds: list[Fold] = generate_splits(task.outer_split, table, seed=task.seed)

    families = list(task.candidate_models)
    all_families = families + list(BASELINE_FAMILIES)
    fold_results: dict[ModelFamily, list[FoldResult]] = {family: [] for family in all_families}
    warnings: list[str] = []

    for fold_index, (train_idx, test_idx) in enumerate(outer_folds):
        fold_data = _FoldData(
            x_train=x[train_idx],
            y_train=y[train_idx],
            x_test=x[test_idx],
            y_test=y[test_idx],
            groups_train=[groups[i] for i in train_idx],
            groups_test=[groups[i] for i in test_idx],
            years_train=[years[i] for i in train_idx],
            sectors_train=[sectors[i] for i in train_idx],
            coords_train=coords_m[train_idx],
            train_size=len(train_idx),
            test_size=len(test_idx),
            test_index=tuple(int(index) for index in test_idx),
        )
        for family in families:
            fold_results[family].append(
                _evaluate_candidate(family, fold_data, fold_index, task, feature_names, warnings)
            )
        for family in BASELINE_FAMILIES:
            fold_results[family].append(_evaluate_baseline(family, fold_data, fold_index, task))

    aggregated = _aggregate_folds(fold_results, all_families, task)

    # every ML candidate must beat or match the best baseline on the primary metric
    baseline_scores = {
        family.value: aggregated[family.value].get(f"{task.primary_metric}_mean", float("inf"))
        for family in BASELINE_FAMILIES
    }
    best_baseline = min(baseline_scores, key=lambda key: baseline_scores[key])
    candidates = {
        family.value: aggregated[family.value].get(f"{task.primary_metric}_mean", float("inf"))
        for family in families
    }
    if candidates:
        selected = min(candidates, key=lambda key: candidates[key])
        if candidates[selected] > baseline_scores[best_baseline] * 1.0001:
            warnings.append(
                f"No candidate model beat the best baseline ({best_baseline}); "
                "the selected model does not improve on climatology."
            )
        selected_family = ModelFamily(selected)
    else:
        selected_family = families[0]
        warnings.append("No candidate models were evaluated.")

    # final refit on ALL data, only after every outer fold was evaluated
    best = bounded_search(
        selected_family,
        x,
        y,
        groups,
        budget=task.search_budget,
        seed=task.seed,
        primary_metric=task.primary_metric,
        inner_strategy=task.inner_split,
        years=years,
        sectors=sectors,
        coords_m=coords_m,
    )
    preprocessor = build_preprocessor(feature_names)
    preprocessor.fit(x, y)
    final_model = make_model(
        ModelSpec(family=selected_family, params=best.best_params, seed=task.seed)
    )
    final_model.fit(preprocessor.transform(x), y, groups)
    final_payload = save_model(final_model, preprocessor, list(feature_names), task)
    import hashlib

    final_sha = hashlib.sha256(final_payload).hexdigest()

    return TrainingResult(
        task_hash=task_hash,
        feature_names=tuple(feature_names),
        feature_table_sha256=feature_table_sha256,
        folds=tuple(fold for family in all_families for fold in fold_results[family]),
        aggregated=aggregated,
        baseline_comparison={key: aggregated[key] for key in baseline_scores},
        selected_family=selected_family,
        selected_params=best.best_params,
        final_model_sha256=final_sha,
        warnings=tuple(warnings),
        final_model=final_model,
        final_preprocessor=preprocessor,
    )


def fit_fold_model(
    family: ModelFamily,
    params: dict[str, Any],
    seed: int,
    feature_names: Sequence[str],
    x_train: np.ndarray,
    y_train: np.ndarray,
    groups_train: list[str],
    x_test: np.ndarray,
    y_test: np.ndarray,
    groups_test: list[str],
    fold_index: int,
    warnings: list[str],
) -> FoldResult:
    """Fit one fold's model with preprocessing fitted on the outer-train only.

    The preprocessing pipeline is fitted on ``x_train`` and never sees
    ``x_test``; the returned fold result carries it so the property can be
    verified.
    """
    preprocessor = build_preprocessor(feature_names)
    preprocessor.fit(x_train, y_train)
    x_train_t = preprocessor.transform(x_train)
    x_test_t = preprocessor.transform(x_test)

    model = make_model(ModelSpec(family=family, params=dict(params), seed=seed))
    model.fit(x_train_t, y_train, groups_train)
    y_pred = np.asarray(model.predict(x_test_t, groups_test), dtype=float)
    if family is ModelFamily.STATION_CLIMATOLOGY:
        unseen = {group for group in groups_test if group not in set(groups_train)}
        if unseen:
            warnings.append(
                f"fold {fold_index}: station climatology fell back to the global "
                f"mean for {len(unseen)} unseen stations"
            )
    metrics = regression_metrics(y_test, y_pred)
    return FoldResult(
        fold_index=fold_index,
        family=family,
        train_size=len(x_train),
        test_size=len(x_test),
        metrics=metrics,
        y_true=y_test,
        y_pred=y_pred,
        warnings=(),
        preprocessor=preprocessor,
    )
