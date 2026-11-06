"""The spatial pipeline: per parameter and timestamp, fit, validate, and store.

The pipeline never overwrites one method's output with another's. When a
selection rule is declared, the decision and its validation evidence are
recorded, but every method's rasters stay stored separately.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

import numpy as np

from trendsmapp.constants import DEFAULT_ANALYSIS_CRS, MAX_UNIQUE_TIMESTAMPS_PER_RUN
from trendsmapp.domain.enums import QcStatus, SpatialMethod
from trendsmapp.domain.models import Observation
from trendsmapp.errors import ResourceLimitError, ValidationError
from trendsmapp.geospatial.boundary import BoundaryDocument
from trendsmapp.geospatial.crs import transform_points
from trendsmapp.geospatial.grid import Grid, build_grid
from trendsmapp.spatial.base import FoldMetrics, SpatialMethodSpec
from trendsmapp.spatial.raster import write_geotiff, write_masked_png
from trendsmapp.spatial.registry import capability_for, fit_method
from trendsmapp.spatial.uncertainty import normalize_uncertainty
from trendsmapp.spatial.validation import leave_one_station_out, spatial_block_holdout

__all__ = [
    "ArtifactSink",
    "FrameMethodResult",
    "FrameResult",
    "SelectionDecision",
    "SpatialRecipe",
    "SpatialRunResult",
    "run_spatial_analysis",
]

#: Minimum observations needed to fit a frame.
MIN_FRAME_POINTS: Final[int] = 3

#: Artifact sink: writes bytes and returns a storage key. In production this
#: closes over the object store and the artifact repository.
ArtifactSink = Callable[[str, str, bytes, str, dict[str, Any]], str]


@dataclass(frozen=True, slots=True)
class SpatialRecipe:
    """The spatial section of an analysis recipe."""

    methods: tuple[SpatialMethodSpec, ...]
    grid_resolution_m: float
    max_grid_cells: int
    analysis_crs: str = DEFAULT_ANALYSIS_CRS
    validation: str = "leave_one_station_out"
    selection_rule: str = "none"
    permitted_qc_statuses: tuple[str, ...] = (QcStatus.PASS.value, QcStatus.WARNING.value)

    def __post_init__(self) -> None:
        if not self.methods:
            raise ValidationError("The recipe must select at least one spatial method.")
        if self.validation not in {"leave_one_station_out", "spatial_block", "none"}:
            raise ValidationError(
                f"Unknown validation '{self.validation}'.",
                details={"allowed": ["leave_one_station_out", "spatial_block", "none"]},
            )
        if self.selection_rule not in {"none", "best_rmse"}:
            raise ValidationError(
                f"Unknown selection rule '{self.selection_rule}'.",
                details={"allowed": ["none", "best_rmse"]},
            )
        for spec in self.methods:
            capability_for(spec.method)


@dataclass(frozen=True, slots=True)
class FrameMethodResult:
    """One method's outcome on one frame."""

    method: SpatialMethod
    metrics: FoldMetrics | None
    geotiff_key: str
    png_key: str
    geotiff_sha256: str
    png_sha256: str
    uncertainty_kind: str
    support_max_m: float


@dataclass(frozen=True, slots=True)
class SelectionDecision:
    """The recorded selection for one frame, when a rule is declared."""

    parameter_id: str
    sampled_at: datetime
    selected_method: SpatialMethod
    rule: str
    evidence: dict[str, float]


@dataclass(frozen=True, slots=True)
class FrameResult:
    """One (parameter, timestamp) frame."""

    parameter_id: str
    sampled_at: datetime
    point_count: int
    skipped_reason: str | None
    methods: tuple[FrameMethodResult, ...] = ()
    mean_geotiff_key: str | None = None
    decisions: tuple[SelectionDecision, ...] = ()


@dataclass(frozen=True, slots=True)
class SpatialRunResult:
    """The outcome of one spatial run."""

    frames: tuple[FrameResult, ...]
    grid_cells: int
    masked_cells: int
    boundary_sha256: str
    analysis_crs: str


def run_spatial_analysis(
    *,
    observations: Sequence[Observation],
    recipe: SpatialRecipe,
    boundary: BoundaryDocument,
    sink: ArtifactSink,
    max_timestamps_per_run: int = MAX_UNIQUE_TIMESTAMPS_PER_RUN,
) -> SpatialRunResult:
    """Run the spatial pipeline over the observations of one dataset version."""
    grid = build_grid(
        boundary.geometry,
        resolution_m=recipe.grid_resolution_m,
        crs=recipe.analysis_crs,
        max_cells=recipe.max_grid_cells,
    )
    grid_points = grid.cell_center_points()

    frames = _group_frames(observations, recipe, max_timestamps_per_run)
    results: list[FrameResult] = []
    for (parameter_id, sampled_at), frame_observations in frames:
        results.append(
            _run_frame(
                parameter_id=parameter_id,
                sampled_at=sampled_at,
                frame_observations=frame_observations,
                recipe=recipe,
                grid=grid,
                grid_points=grid_points,
                sink=sink,
            )
        )
    return SpatialRunResult(
        frames=tuple(results),
        grid_cells=grid.cell_count,
        masked_cells=grid.masked_cell_count,
        boundary_sha256=boundary.sha256,
        analysis_crs=grid.crs,
    )


def _group_frames(
    observations: Sequence[Observation],
    recipe: SpatialRecipe,
    max_timestamps: int,
) -> list[tuple[tuple[str, datetime], list[Observation]]]:
    """Group permitted observations by (parameter, timestamp), deterministically."""
    permitted = {QcStatus(status) for status in recipe.permitted_qc_statuses}
    groups: dict[tuple[str, datetime], list[Observation]] = {}
    for observation in observations:
        if observation.is_excluded:
            continue
        if observation.qc_status not in permitted:
            continue
        if observation.canonical_value is None or not observation.parameter_id:
            continue
        groups.setdefault((observation.parameter_id, observation.sampled_at), []).append(
            observation
        )
    timestamps = sorted({sampled_at for _, sampled_at in groups})
    if len(timestamps) > max_timestamps:
        raise ResourceLimitError(
            "The run would produce more frames than the per-run timestamp cap.",
            details={"timestamps": len(timestamps), "max_timestamps_per_run": max_timestamps},
        )
    ordered = sorted(groups.items(), key=lambda item: (item[0][0], item[0][1]))
    return ordered


def _fit_predict_factory(
    spec: SpatialMethodSpec, crs: str
) -> Callable[[np.ndarray, np.ndarray, np.ndarray], np.ndarray]:
    """Return a typed fit-and-predict function for one method spec."""

    def fit_predict(
        train_points: np.ndarray, train_values: np.ndarray, test_points: np.ndarray
    ) -> np.ndarray:
        """Fit the spec on the training split and predict the test points."""
        return fit_method(spec, train_points, train_values, crs=crs).predict(test_points).values

    return fit_predict


def _run_frame(
    *,
    parameter_id: str,
    sampled_at: datetime,
    frame_observations: list[Observation],
    recipe: SpatialRecipe,
    grid: Grid,
    grid_points: np.ndarray,
    sink: ArtifactSink,
) -> FrameResult:
    """Fit, validate, and store every method on one frame."""
    if len(frame_observations) < MIN_FRAME_POINTS:
        return FrameResult(
            parameter_id=parameter_id,
            sampled_at=sampled_at,
            point_count=len(frame_observations),
            skipped_reason=(
                f"only {len(frame_observations)} permitted observations; "
                f"{MIN_FRAME_POINTS} required"
            ),
        )

    lonlat = np.array(
        [[o.longitude_wgs84, o.latitude_wgs84] for o in frame_observations], dtype=float
    )
    points = transform_points(lonlat, source_crs="EPSG:4326", target_crs=grid.crs)
    values = np.array([o.canonical_value for o in frame_observations], dtype=float)
    station_ids = [o.station_id for o in frame_observations]

    def fit_predict(
        train_points: np.ndarray, train_values: np.ndarray, test_points: np.ndarray
    ) -> np.ndarray:
        spec = recipe.methods[0]
        fitted = fit_method(spec, train_points, train_values, crs=grid.crs)
        return fitted.predict(test_points).values

    method_results: list[FrameMethodResult] = []
    surfaces: list[np.ndarray] = []
    for spec in recipe.methods:
        fitted = fit_method(spec, points, values, crs=grid.crs)
        prediction = fitted.predict(grid_points)
        surface = prediction.values.reshape(grid.n_rows, grid.n_cols)

        metrics: FoldMetrics | None = None
        if recipe.validation == "leave_one_station_out":
            metrics = leave_one_station_out(
                points,
                values,
                station_ids,
                spec=spec,
                crs=grid.crs,
                fit_predict=_fit_predict_factory(spec, grid.crs),
            )
        elif recipe.validation == "spatial_block":
            metrics = spatial_block_holdout(
                points,
                values,
                spec=spec,
                crs=grid.crs,
                fit_predict=_fit_predict_factory(spec, grid.crs),
            )

        geotiff = write_geotiff(surface, grid)
        png = write_masked_png(surface, grid)
        geotiff_key = sink(
            "runs",
            f"spatial/{parameter_id}/{sampled_at.isoformat()}/{spec.method.value}.tif",
            geotiff.payload,
            "image/tiff",
            {
                "parameter_id": parameter_id,
                "sampled_at": sampled_at.isoformat(),
                "method": spec.method.value,
                "kind": "geotiff",
                "sha256": geotiff.sha256,
                "extent": list(grid.extent()),
                "crs": grid.crs,
            },
        )
        png_key = sink(
            "runs",
            f"spatial/{parameter_id}/{sampled_at.isoformat()}/{spec.method.value}.png",
            png.payload,
            "image/png",
            {
                "parameter_id": parameter_id,
                "sampled_at": sampled_at.isoformat(),
                "method": spec.method.value,
                "kind": "png",
                "sha256": png.sha256,
            },
        )
        uncertainty = normalize_uncertainty(
            spec.method, raw_uncertainty=prediction.uncertainty, support_m=prediction.support
        )
        sink(
            "runs",
            f"spatial/{parameter_id}/{sampled_at.isoformat()}/{spec.method.value}.uncertainty.json",
            _json_bytes(uncertainty),
            "application/json",
            {
                "parameter_id": parameter_id,
                "sampled_at": sampled_at.isoformat(),
                "method": spec.method.value,
                "uncertainty_kind": uncertainty.kind,
            },
        )
        method_results.append(
            FrameMethodResult(
                method=spec.method,
                metrics=metrics,
                geotiff_key=geotiff_key,
                png_key=png_key,
                geotiff_sha256=geotiff.sha256,
                png_sha256=png.sha256,
                uncertainty_kind=uncertainty.kind,
                support_max_m=float(prediction.support.max()) if len(prediction.support) else 0.0,
            )
        )
        surfaces.append(surface)

    mean_surface = np.nanmean(np.stack(surfaces), axis=0)
    mean_geotiff = write_geotiff(mean_surface, grid)
    mean_key = sink(
        "runs",
        f"spatial/{parameter_id}/{sampled_at.isoformat()}/mean.tif",
        mean_geotiff.payload,
        "image/tiff",
        {
            "parameter_id": parameter_id,
            "sampled_at": sampled_at.isoformat(),
            "kind": "mean_geotiff",
            "methods": [s.method.value for s in recipe.methods],
            "sha256": mean_geotiff.sha256,
        },
    )

    decisions: list[SelectionDecision] = []
    if recipe.selection_rule == "best_rmse":
        candidates = [
            (result, result.metrics)
            for result in method_results
            if result.metrics is not None and result.metrics.fold_count > 0
        ]
        if candidates:
            best = min(candidates, key=lambda item: (item[1].rmse, item[0].method.value))
            decisions.append(
                SelectionDecision(
                    parameter_id=parameter_id,
                    sampled_at=sampled_at,
                    selected_method=best[0].method,
                    rule=recipe.selection_rule,
                    evidence={
                        result.method.value: metrics.rmse
                        for result, metrics in candidates
                        if metrics is not None
                    },
                )
            )

    return FrameResult(
        parameter_id=parameter_id,
        sampled_at=sampled_at,
        point_count=len(frame_observations),
        skipped_reason=None,
        methods=tuple(method_results),
        mean_geotiff_key=mean_key,
        decisions=tuple(decisions),
    )


def _json_bytes(payload: Any) -> bytes:
    """Serialize a payload deterministically."""
    import json

    return json.dumps(payload, default=_json_default, sort_keys=True).encode("utf-8")


def _json_default(value: Any) -> Any:
    """Serialize numpy scalars and arrays for JSON."""
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    return str(value)
