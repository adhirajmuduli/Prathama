"""Renderer-neutral result tables serialized as CSV bytes.

Tables are the interchange format between the worker, the export bundle, and
the frontend: the same numbers appear in a figure, a table, and an export
without a second computation. Every function is pure and deterministic, and
list or dict cell values are JSON-encoded so a cell never breaks the CSV.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

__all__ = [
    "analysis_frames_table",
    "explanations_table",
    "folds_table",
    "metrics_table",
    "predictions_table",
    "result_tables",
    "table_csv",
]


def _cell(value: Any) -> Any:
    """Return a CSV-safe cell value."""
    if isinstance(value, (list, dict)):
        return json.dumps(value, sort_keys=True)
    return value


def table_csv(columns: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> bytes:
    """Serialize rows as CSV bytes with a header line and LF newlines."""
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(columns), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: _cell(row.get(column, "")) for column in columns})
    return buffer.getvalue().encode("utf-8")


def metrics_table(results: Mapping[str, Any]) -> bytes:
    """One row per model family and aggregated metric of an ML results document."""
    aggregated = results.get("aggregated")
    if not isinstance(aggregated, dict):
        return table_csv(["family", "metric", "value"], [])
    rows: list[dict[str, Any]] = []
    for family in sorted(aggregated):
        metrics = aggregated[family]
        if not isinstance(metrics, dict):
            continue
        for metric in sorted(metrics):
            rows.append({"family": family, "metric": metric, "value": metrics[metric]})
    return table_csv(["family", "metric", "value"], rows)


def folds_table(results: Mapping[str, Any]) -> bytes:
    """One row per outer fold and family, with the fold's metrics as columns."""
    folds = results.get("folds")
    if not isinstance(folds, list):
        return table_csv(["fold_index", "family", "train_size", "test_size"], [])
    metric_keys = sorted(
        {key for fold in folds if isinstance(fold.get("metrics"), dict) for key in fold["metrics"]}
    )
    columns = ["fold_index", "family", "train_size", "test_size", *metric_keys]
    rows = []
    for fold in folds:
        if not isinstance(fold, dict):
            continue
        row: dict[str, Any] = {
            "fold_index": fold.get("fold_index"),
            "family": fold.get("family"),
            "train_size": fold.get("train_size"),
            "test_size": fold.get("test_size"),
        }
        metrics = fold.get("metrics")
        if isinstance(metrics, dict):
            for key in metric_keys:
                row[key] = metrics.get(key)
        rows.append(row)
    return table_csv(columns, rows)


def predictions_table(predictions: Mapping[str, Any]) -> bytes:
    """One row per held-out row: observed versus predicted, per fold and family."""
    folds = predictions.get("folds")
    if not isinstance(folds, list):
        return table_csv(["fold_index", "family", "row_index", "y_true", "y_pred"], [])
    rows: list[dict[str, Any]] = []
    for fold in folds:
        if not isinstance(fold, dict):
            continue
        y_true = fold.get("y_true") or []
        y_pred = fold.get("y_pred") or []
        for row_index, (truth, predicted) in enumerate(zip(y_true, y_pred, strict=False)):
            rows.append(
                {
                    "fold_index": fold.get("fold_index"),
                    "family": fold.get("family"),
                    "row_index": row_index,
                    "y_true": truth,
                    "y_pred": predicted,
                }
            )
    return table_csv(["fold_index", "family", "row_index", "y_true", "y_pred"], rows)


def explanations_table(explanations: Mapping[str, Any]) -> bytes:
    """One row per explanation importance entry of a model run."""
    rows_in = explanations.get("rows")
    if not isinstance(rows_in, list):
        return table_csv(["feature", "method", "value", "baseline", "unit", "group", "rank"], [])
    columns = ["feature", "method", "value", "baseline", "unit", "group", "rank"]
    return table_csv(columns, [row for row in rows_in if isinstance(row, dict)])


def analysis_frames_table(summary: Mapping[str, Any]) -> bytes:
    """One row per spatial method and frame of an analysis results document."""
    frames = summary.get("frames")
    if not isinstance(frames, list):
        return table_csv(
            ["parameter_id", "sampled_at", "point_count", "method", "rmse", "mae", "bias", "folds"],
            [],
        )
    columns = [
        "parameter_id",
        "sampled_at",
        "point_count",
        "skipped_reason",
        "method",
        "rmse",
        "mae",
        "bias",
        "folds",
        "selected",
    ]
    rows: list[dict[str, Any]] = []
    for frame in frames:
        if not isinstance(frame, dict):
            continue
        decisions = frame.get("decisions") or []
        selected = next(
            (
                str(d.get("selected"))
                for d in decisions
                if isinstance(d, dict) and d.get("selected")
            ),
            "",
        )
        methods = frame.get("methods") or []
        if not methods:
            rows.append(
                {
                    "parameter_id": frame.get("parameter_id"),
                    "sampled_at": frame.get("sampled_at"),
                    "point_count": frame.get("point_count"),
                    "skipped_reason": frame.get("skipped_reason"),
                    "method": "",
                    "selected": selected,
                }
            )
            continue
        for method in methods:
            if not isinstance(method, dict):
                continue
            rows.append(
                {
                    "parameter_id": frame.get("parameter_id"),
                    "sampled_at": frame.get("sampled_at"),
                    "point_count": frame.get("point_count"),
                    "skipped_reason": frame.get("skipped_reason"),
                    "method": method.get("method"),
                    "rmse": method.get("rmse"),
                    "mae": method.get("mae"),
                    "bias": method.get("bias"),
                    "folds": method.get("folds"),
                    "selected": selected,
                }
            )
    return table_csv(columns, rows)


def result_tables(documents: Mapping[str, Mapping[str, Any]]) -> dict[str, bytes]:
    """Build every CSV table the stored run documents support.

    ``documents`` maps a document role (``metrics``, ``predictions``,
    ``explanations``) to the parsed JSON document. ML results produce the
    metrics/folds/predictions/explanations tables; an analysis summary produces
    the frames table. A document of an unrecognized shape is skipped, never
    guessed at.
    """
    tables: dict[str, bytes] = {}
    metrics = documents.get("metrics")
    if isinstance(metrics, Mapping):
        if isinstance(metrics.get("aggregated"), dict):
            tables["ml-metrics.csv"] = metrics_table(metrics)
            tables["ml-folds.csv"] = folds_table(metrics)
        elif isinstance(metrics.get("frames"), list):
            tables["analysis-frames.csv"] = analysis_frames_table(metrics)
    predictions = documents.get("predictions")
    if isinstance(predictions, Mapping) and isinstance(predictions.get("folds"), list):
        tables["ml-predictions.csv"] = predictions_table(predictions)
    explanations = documents.get("explanations")
    if isinstance(explanations, Mapping) and isinstance(explanations.get("rows"), list):
        tables["ml-explanations.csv"] = explanations_table(explanations)
    return tables
