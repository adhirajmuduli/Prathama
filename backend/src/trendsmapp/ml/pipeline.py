"""End-to-end ML task pipeline: task validation, feature generation with lineage,
outer/inner training, evaluation, uncertainty, and result storage.

Features are built from the sealed dataset version's observations. Lag features
come from the same station's own earlier observations — never from the test row
or its future. The feature table is hashed, and every feature's source is
recorded in the lineage so a reviewer can trace each column.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

import numpy as np

from trendsmapp.constants import DEFAULT_ANALYSIS_CRS
from trendsmapp.contracts.tasks import MLTask, task_hash
from trendsmapp.domain.enums import QcStatus
from trendsmapp.domain.models import Observation
from trendsmapp.errors import ResourceLimitError, ValidationError
from trendsmapp.geospatial.crs import transform_points
from trendsmapp.ml.artifacts import save_model as default_save_model
from trendsmapp.ml.training import TrainingResult, train_and_evaluate
from trendsmapp.ml.uncertainty import UncertaintyResult, compute_uncertainty
from trendsmapp.temporal.seasonal import label_for

__all__ = [
    "LAG_POLICIES",
    "MIN_FRAME_ROWS",
    "FeatureFrame",
    "MLRunResult",
    "build_feature_frame",
    "run_ml_task",
    "uncertainty_for_selected",
]

#: Minimum rows a task needs to train.
MIN_FRAME_ROWS: Final[int] = 20

#: Lag feature definitions: name -> (offset days, tolerance days).
_LAGS: Final[dict[str, tuple[float, float]]] = {
    "lag_1d": (1.0, 2.0),
    "lag_7d": (7.0, 2.0),
    "lag_28d": (28.0, 2.0),
}

#: Which lags each lag policy includes.
LAG_POLICIES: Final[dict[str, tuple[str, ...]]] = {
    "none": (),
    "daily": ("lag_1d",),
    "weekly": ("lag_1d", "lag_7d"),
    "monthly": ("lag_1d", "lag_7d", "lag_28d"),
    "all": ("lag_1d", "lag_7d", "lag_28d"),
}

CALENDAR_FEATURES: Final[tuple[str, ...]] = ("day_of_year", "month", "season")
SPATIAL_FEATURES: Final[tuple[str, ...]] = ("x_m", "y_m")


@dataclass(frozen=True, slots=True)
class FeatureFrame:
    """The feature matrix and its per-row grouping arrays."""

    x: np.ndarray
    y: np.ndarray
    groups: list[str]
    years: list[int]
    sectors: list[str]
    coords_m: np.ndarray
    feature_names: tuple[str, ...]
    lineage: dict[str, str]
    sha256: str


@dataclass(frozen=True, slots=True)
class MLRunResult:
    """The outcome of one ML task run."""

    task_hash: str
    feature_frame: FeatureFrame
    training: TrainingResult
    uncertainty: UncertaintyResult
    model_sha256: str
    model_storage_key: str | None
    results_storage_key: str | None
    warnings: tuple[str, ...]


def _require_value(observation: Observation) -> float:
    """Return the canonical value, which the row filter guarantees is present."""
    if observation.canonical_value is None:
        raise ValidationError(
            "An observation without a canonical value reached the feature builder.",
            details={"observation_id": observation.observation_id},
        )
    return observation.canonical_value


def _parse_bound(text: str | None) -> datetime | None:
    """Parse an eligible date bound as an aware UTC instant.

    A bound without an offset is interpreted as UTC, matching the timezone
    policy the rest of the pipeline applies. A naive bound compared against
    aware observations would otherwise raise.
    """
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValidationError(
            f"'{text}' is not a valid ISO 8601 timestamp.",
            details={"reason": "invalid_eligible_bound", "value": text},
        ) from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def build_feature_frame(observations: Sequence[Observation], task: MLTask) -> FeatureFrame:
    """Build the feature frame for a task from sealed observations.

    Rows are filtered by the task's target parameter, eligible date range,
    eligible stations, QC/exclusion policy, and presence of a canonical value.
    """
    start = _parse_bound(task.eligible_start)
    end = _parse_bound(task.eligible_end)
    if start is not None and end is not None and start > end:
        raise ValidationError(
            "The eligible start is after the eligible end.",
            details={"reason": "inverted_eligible_range"},
        )
    stations = set(task.eligible_station_ids) if task.eligible_station_ids else None
    exclude_failed = task.qc_policy == "exclude_failed"

    selected = [
        o
        for o in observations
        if o.parameter_id == task.target_parameter_id
        and o.canonical_value is not None
        and not o.is_excluded
        and not (exclude_failed and o.qc_status is QcStatus.FAIL)
        and (start is None or o.sampled_at >= start)
        and (end is None or o.sampled_at <= end)
        and (stations is None or o.station_id in stations)
    ]
    if len(selected) < MIN_FRAME_ROWS:
        raise ResourceLimitError(
            f"The task has only {len(selected)} usable rows; at least "
            f"{MIN_FRAME_ROWS} are required.",
            details={"rows": len(selected), "min_rows": MIN_FRAME_ROWS},
        )

    lag_names = LAG_POLICIES.get(task.lag_policy, LAG_POLICIES["all"])
    feature_names = lag_names + CALENDAR_FEATURES + SPATIAL_FEATURES
    lineage: dict[str, str] = {
        name: f"value of the same station {offset}d earlier"
        for name, (offset, _tol) in _LAGS.items()
        if name in lag_names
    }
    lineage.update(
        {
            "day_of_year": "calendar day of the observation",
            "month": "calendar month of the observation",
            "season": "meteorological season of the observation",
            "x_m": "easting in the analysis CRS",
            "y_m": "northing in the analysis CRS",
        }
    )

    # Per-station series for lag features. Rows keep the order of `selected`;
    # lag values are stored by the row's position in `selected`.
    series_pos: dict[str, list[int]] = {}
    for row_index, o in enumerate(selected):
        series_pos.setdefault(o.station_id, []).append(row_index)
    lag_values: dict[str, list[float]] = {
        name: [float("nan")] * len(selected) for name in lag_names
    }
    for _station, positions in series_pos.items():
        times = np.asarray([selected[p].sampled_at.timestamp() for p in positions], dtype=float)
        values = np.asarray([_require_value(selected[p]) for p in positions], dtype=float)
        for name, (offset_days, tol_days) in _LAGS.items():
            if name not in lag_names:
                continue
            target = times - offset_days * 86_400.0
            pos = np.searchsorted(times, target)
            for local_i, p in enumerate(pos):
                # Only a strictly earlier observation may supply a lag value;
                # the row itself must never be its own lag.
                if p >= local_i or p >= len(times):
                    continue
                if abs(times[p] - target[local_i]) <= tol_days * 86_400.0:
                    lag_values[name][positions[local_i]] = float(values[p])

    season_labels = sorted({label_for(o.sampled_at) or "unlabeled" for o in selected})
    season_index = {label: index for index, label in enumerate(season_labels)}

    lonlat = np.asarray([[o.longitude_wgs84, o.latitude_wgs84] for o in selected], dtype=float)
    coords = transform_points(lonlat, source_crs="EPSG:4326", target_crs=DEFAULT_ANALYSIS_CRS)

    rows: list[list[float]] = []
    y: list[float] = []
    groups: list[str] = []
    years: list[int] = []
    sectors: list[str] = []
    for row_index, o in enumerate(selected):
        row: list[float] = []
        for name in lag_names:
            row.append(lag_values[name][row_index])
        row.append(float(o.sampled_at.timetuple().tm_yday))
        row.append(float(o.sampled_at.month))
        row.append(float(season_index[label_for(o.sampled_at) or "unlabeled"]))
        row.append(float(coords[row_index, 0]))
        row.append(float(coords[row_index, 1]))
        rows.append(row)
        y.append(_require_value(o))
        groups.append(o.station_id)
        years.append(o.sampled_at.year)
        sectors.append(o.sector or "unassigned")

    x = np.asarray(rows, dtype=float)
    y_arr = np.asarray(y, dtype=float)
    digest = hashlib.sha256(
        json.dumps(
            {
                "features": list(feature_names),
                "rows": np.round(x, 6).tolist(),
                "y": np.round(y_arr, 6).tolist(),
                "groups": groups,
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return FeatureFrame(
        x=x,
        y=y_arr,
        groups=groups,
        years=years,
        sectors=sectors,
        coords_m=coords,
        feature_names=tuple(feature_names),
        lineage=lineage,
        sha256=digest,
    )


def run_ml_task(
    task: MLTask,
    observations: Sequence[Observation],
    *,
    save_model: Callable[..., bytes] = default_save_model,
    sink: Callable[[str, str, bytes, str, dict[str, Any]], str] | None = None,
) -> MLRunResult:
    """Run one ML task end to end: features, training, evaluation, uncertainty, storage."""
    frame = build_feature_frame(observations, task)
    digest = task_hash(task)
    training = train_and_evaluate(
        task,
        x=frame.x,
        y=frame.y,
        groups=frame.groups,
        years=frame.years,
        sectors=frame.sectors,
        coords_m=frame.coords_m,
        feature_names=frame.feature_names,
        feature_table_sha256=frame.sha256,
        task_hash=digest,
        save_model=save_model,
    )

    uncertainty = uncertainty_for_selected(task, frame, training)

    model_key = None
    results_key = None
    if sink is not None:
        payload = _final_model_payload(task, frame, training, save_model)
        model_key = sink(
            "model",
            f"model-{digest[:12]}.pkg",
            payload,
            "application/octet-stream",
            {"task_hash": digest, "family": training.selected_family.value},
        )
        results_key = sink(
            "metrics",
            f"ml-results-{digest[:12]}.json",
            json.dumps(
                _result_summary(task, frame, training, uncertainty, digest),
                indent=2,
                sort_keys=True,
                default=str,
            ).encode("utf-8"),
            "application/json",
            {"task_hash": digest},
        )
    return MLRunResult(
        task_hash=digest,
        feature_frame=frame,
        training=training,
        uncertainty=uncertainty,
        model_sha256=training.final_model_sha256,
        model_storage_key=model_key,
        results_storage_key=results_key,
        warnings=training.warnings + uncertainty.notes,
    )


def _final_model_payload(
    task: MLTask,
    frame: FeatureFrame,
    training: TrainingResult,
    save_model: Callable[..., bytes],
) -> bytes:
    """Serialize the final refit model for storage."""
    from trendsmapp.ml.models import ModelSpec, make_model
    from trendsmapp.ml.preprocessing import build_preprocessor

    preprocessor = build_preprocessor(frame.feature_names)
    preprocessor.fit(frame.x, frame.y)
    model = make_model(
        ModelSpec(
            family=training.selected_family,
            params=training.selected_params,
            seed=task.seed,
        )
    )
    model.fit(preprocessor.transform(frame.x), frame.y, frame.groups)
    return save_model(model, preprocessor, list(frame.feature_names), task)


def uncertainty_for_selected(
    task: MLTask, frame: FeatureFrame, training: TrainingResult
) -> UncertaintyResult:
    """Ensemble intervals for the selected family, pooled over the outer folds.

    Each outer fold is re-evaluated with the task's uncertainty method, so the
    intervals are always computed on rows the fold model never saw during
    fitting. Public because the worker workflow needs the same computation the
    in-process pipeline performs.
    """
    from trendsmapp.ml.models import ModelSpec, make_model
    from trendsmapp.ml.preprocessing import build_preprocessor
    from trendsmapp.ml.splits import FrameTable, generate_splits

    table = FrameTable(
        station_ids=frame.groups,
        years=frame.years,
        sectors=frame.sectors,
        coords_m=frame.coords_m,
        timestamps=[None] * len(frame.groups),
    )
    folds = generate_splits(task.outer_split, table, seed=task.seed)

    def fit_predict(
        x_tr: np.ndarray, y_tr: np.ndarray, seed: int
    ) -> Callable[[np.ndarray], np.ndarray]:
        pre = build_preprocessor(frame.feature_names)
        pre.fit(x_tr, y_tr)
        model = make_model(
            ModelSpec(
                family=training.selected_family,
                params=training.selected_params,
                seed=seed,
            )
        )
        model.fit(pre.transform(x_tr), y_tr)
        return lambda x_te: np.asarray(model.predict(pre.transform(x_te)), dtype=float)

    lowers: list[np.ndarray] = []
    uppers: list[np.ndarray] = []
    truths: list[np.ndarray] = []
    for train_idx, test_idx in folds:
        result = compute_uncertainty(
            task.uncertainty_method,
            fit_predict=fit_predict,
            x_train=frame.x[train_idx],
            y_train=frame.y[train_idx],
            x_test=frame.x[test_idx],
            y_test=frame.y[test_idx],
            seed=task.seed,
        )
        lowers.append(result.lower)
        uppers.append(result.upper)
        truths.append(frame.y[test_idx])
    lower = np.concatenate(lowers)
    upper = np.concatenate(uppers)
    truth = np.concatenate(truths)
    coverage = float(np.mean((truth >= lower) & (truth <= upper)))
    return UncertaintyResult(
        method=task.uncertainty_method,
        lower=lower,
        upper=upper,
        empirical_coverage=coverage,
        notes=tuple(training.warnings),
    )


def _result_summary(
    task: MLTask,
    frame: FeatureFrame,
    training: TrainingResult,
    uncertainty: UncertaintyResult,
    digest: str,
) -> dict[str, Any]:
    """The stored results document of one ML run."""
    return {
        "task_hash": digest,
        "task": task.model_dump(mode="json"),
        "feature_names": list(frame.feature_names),
        "feature_lineage": frame.lineage,
        "feature_table_sha256": frame.sha256,
        "rows": len(frame.y),
        "folds": len({fold.fold_index for fold in training.folds}),
        "aggregated": training.aggregated,
        "baseline_comparison": training.baseline_comparison,
        "selected_family": training.selected_family.value,
        "selected_params": training.selected_params,
        "final_model_sha256": training.final_model_sha256,
        "uncertainty": {
            "method": uncertainty.method.value,
            "empirical_coverage": uncertainty.empirical_coverage,
        },
        "warnings": list(training.warnings) + list(uncertainty.notes),
    }
