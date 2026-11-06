"""The analyze workflow: the worker's handler for ``analyze`` jobs.

One analyze job reads the sealed dataset version, runs the spatial and temporal
pipelines declared by the recipe, stores every output as a digest-verified
artifact tied to the run, and finishes the run row. Cancellation is checked
between stages.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Final

from trendsmapp.contracts.recipes import Recipe
from trendsmapp.contracts.versions import ARTIFACT_SCHEMA_VERSION
from trendsmapp.domain.enums import JobType
from trendsmapp.domain.identifiers import new_artifact_id
from trendsmapp.errors import JobError
from trendsmapp.geospatial.boundary import load_default_boundary
from trendsmapp.normalization.pipeline import observations_from_parquet
from trendsmapp.persistence.database import session_scope
from trendsmapp.persistence.repositories import (
    ArtifactRepository,
    DatasetRepository,
    RunRepository,
)
from trendsmapp.spatial.pipeline import run_spatial_analysis
from trendsmapp.storage.paths import build_artifact_key
from trendsmapp.temporal.pipeline import run_temporal_analysis
from trendsmapp.worker.handlers import JobExecutionContext, JobHandlerRegistry

__all__ = ["AnalyzeWorkflow", "register_analysis_handlers"]

_STAGE_LOAD: Final[str] = "load"
_STAGE_SPATIAL: Final[str] = "spatial"
_STAGE_TEMPORAL: Final[str] = "temporal"
_STAGE_STORE: Final[str] = "store"


class AnalyzeWorkflow:
    """Executes one analyze job end to end."""

    async def __call__(self, context: JobExecutionContext) -> dict[str, Any]:
        """Run the analysis described by the job payload."""
        payload = context.payload
        run_id = str(payload.get("run_id", ""))
        recipe_dict = payload.get("recipe")
        if not run_id or not isinstance(recipe_dict, dict):
            raise JobError(
                "The analyze job payload is missing the run or the recipe.",
                details={"has_run": bool(run_id), "has_recipe": isinstance(recipe_dict, dict)},
            )
        recipe = Recipe.model_validate(recipe_dict)

        await self._progress(context, 0.05, _STAGE_LOAD)
        async with session_scope(context.session_factory) as session:
            runs = RunRepository(session)
            datasets = DatasetRepository(session)
            artifacts = ArtifactRepository(session)
            await runs.require(run_id)
            version = await datasets.require_version(recipe.dataset_version_id)
            if version.normalized_artifact_id is None:
                raise JobError(
                    "The dataset version has no normalized artifact.",
                    details={"dataset_version_id": version.id},
                )
            artifact = await artifacts.require(version.normalized_artifact_id)
            with context.object_store.open_stream(artifact.storage_key) as handle:
                observations = observations_from_parquet(handle)

        await self._check_cancel(context)
        await self._progress(context, 0.2, _STAGE_SPATIAL)
        boundary = load_default_boundary()
        spatial_recipe = recipe.spatial.to_spatial_recipe()
        stored: list[dict[str, Any]] = []

        def sink(
            kind: str, name: str, payload_bytes: bytes, content_type: str, metadata: dict[str, Any]
        ) -> str:
            digest = hashlib.sha256(payload_bytes).hexdigest()
            key = build_artifact_key("runs", digest, name.split("/")[-1])
            context.object_store.put_bytes(key, payload_bytes, content_type=content_type)
            # Map the pipeline's storage kind onto the controlled artifact kinds:
            # rasters are "raster", JSON side documents are "other" with their
            # kind in the metadata.
            artifact_kind = "raster" if name.endswith((".tif", ".png")) else "other"
            stored.append(
                {
                    "artifact_id": new_artifact_id(),
                    "kind": artifact_kind,
                    "sha256": digest,
                    "size_bytes": len(payload_bytes),
                    "content_type": content_type,
                    "storage_key": key,
                    "run_id": run_id,
                    "metadata": metadata,
                }
            )
            return key

        spatial_result = run_spatial_analysis(
            observations=observations,
            recipe=spatial_recipe,
            boundary=boundary,
            sink=sink,
        )

        await self._check_cancel(context)
        await self._progress(context, 0.6, _STAGE_TEMPORAL)
        temporal_result = None
        if recipe.temporal is not None:
            temporal_recipe = recipe.temporal.to_temporal_recipe(seed=recipe.seed)
            temporal_result = run_temporal_analysis(
                observations=observations, recipe=temporal_recipe
            )

        await self._progress(context, 0.8, _STAGE_STORE)
        summary = {
            "run_id": run_id,
            "recipe_hash": payload.get("recipe_hash"),
            "frames": [
                {
                    "parameter_id": frame.parameter_id,
                    "sampled_at": frame.sampled_at.isoformat(),
                    "point_count": frame.point_count,
                    "skipped_reason": frame.skipped_reason,
                    "methods": [
                        {
                            "method": method.method.value,
                            "rmse": method.metrics.rmse if method.metrics else None,
                            "mae": method.metrics.mae if method.metrics else None,
                            "bias": method.metrics.bias if method.metrics else None,
                            "folds": method.metrics.fold_count if method.metrics else 0,
                            "geotiff_key": method.geotiff_key,
                            "png_key": method.png_key,
                            "uncertainty_kind": method.uncertainty_kind,
                        }
                        for method in frame.methods
                    ],
                    "decisions": [
                        {
                            "selected": decision.selected_method.value,
                            "rule": decision.rule,
                            "evidence": decision.evidence,
                        }
                        for decision in frame.decisions
                    ],
                }
                for frame in spatial_result.frames
            ],
            "grid_cells": spatial_result.grid_cells,
            "masked_cells": spatial_result.masked_cells,
            "boundary_sha256": spatial_result.boundary_sha256,
            "temporal": (
                {
                    "series": [
                        {
                            "station_id": series.station_id,
                            "parameter_id": series.parameter_id,
                            "observed": series.alignment.observed_count,
                            "missing": series.alignment.missing_count,
                            "frames": len(series.frames),
                            "trend_slope_per_day": (
                                series.trend.slope_per_day if series.trend else None
                            ),
                            "seasonal_counts": series.seasonal_counts,
                        }
                        for series in temporal_result.series
                    ]
                }
                if temporal_result is not None
                else None
            ),
        }
        summary_bytes = json.dumps(summary, indent=2, sort_keys=True, default=str).encode("utf-8")
        stored.append(
            {
                "artifact_id": new_artifact_id(),
                "kind": "metrics",
                "sha256": hashlib.sha256(summary_bytes).hexdigest(),
                "size_bytes": len(summary_bytes),
                "content_type": "application/json",
                "storage_key": build_artifact_key(
                    "runs", hashlib.sha256(summary_bytes).hexdigest(), "analysis-results.json"
                ),
                "run_id": run_id,
                "metadata": {"run_id": run_id, "recipe_hash": payload.get("recipe_hash")},
            }
        )
        context.object_store.put_bytes(
            stored[-1]["storage_key"], summary_bytes, content_type="application/json"
        )

        async with session_scope(context.session_factory) as session:
            artifacts = ArtifactRepository(session)
            for entry in stored:
                await artifacts.register(
                    artifact_id=entry["artifact_id"],
                    kind=entry["kind"],
                    sha256=entry["sha256"],
                    size_bytes=entry["size_bytes"],
                    content_type=entry["content_type"],
                    storage_key=entry["storage_key"],
                    schema_version=ARTIFACT_SCHEMA_VERSION,
                    run_id=entry.get("run_id"),
                    metadata=entry.get("metadata") or {},
                )
            runs = RunRepository(session)
            await runs.finish(run_id, status="succeeded")
        await self._progress(context, 1.0, None)
        return {
            "run_id": run_id,
            "frames": len(spatial_result.frames),
            "artifacts": len(stored),
            "recipe_hash": payload.get("recipe_hash"),
        }

    async def _progress(
        self, context: JobExecutionContext, progress: float, stage: str | None
    ) -> None:
        """Record job progress and heartbeat in one call."""
        await context.heartbeat.record_progress(context.job_id, progress=progress, stage=stage)

    async def _check_cancel(self, context: JobExecutionContext) -> None:
        """Raise when cancellation was requested for the job."""
        if await context.cancellation_probe():
            raise JobError("The job was cancelled.", details={"reason": "cancelled"})


def register_analysis_handlers(registry: JobHandlerRegistry) -> None:
    """Register the analysis handlers on a workflow registry."""
    registry.register(JobType.ANALYZE, AnalyzeWorkflow())
