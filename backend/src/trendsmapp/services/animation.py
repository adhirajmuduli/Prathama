"""The animate workflow: the worker's handler for ``animate`` jobs.

One animate job reads the stored rasters of an analysis run, renders captioned
frames under one global scale, encodes and validates the MP4, and stores the
video, its metadata, and a legend as run artifacts. Frames render from stored
rasters; nothing is re-interpolated here. Cancellation is checked between
frames.
"""

from __future__ import annotations

import hashlib
from typing import Any, Final

from trendsmapp.contracts.versions import ARTIFACT_SCHEMA_VERSION
from trendsmapp.domain.enums import JobType
from trendsmapp.domain.identifiers import new_artifact_id
from trendsmapp.errors import JobError, NotFoundError
from trendsmapp.persistence.database import session_scope
from trendsmapp.persistence.repositories import ArtifactRepository, RunRepository
from trendsmapp.spatial.raster import grid_from_geotiff
from trendsmapp.storage.paths import build_artifact_key
from trendsmapp.temporal.interpolation import FrameStatus
from trendsmapp.visualization.animation import (
    MAX_ANIMATION_FRAMES,
    AnimationFrame,
    AnimationSpec,
    metadata_json,
    render_animation,
)
from trendsmapp.visualization.legend import render_legend_png
from trendsmapp.visualization.palettes import resolve_palette
from trendsmapp.visualization.scales import ScalePolicy, compute_scale
from trendsmapp.worker.handlers import JobExecutionContext, JobHandlerRegistry

__all__ = ["AnimateWorkflow", "register_animate_handler"]

_STAGE_LOAD: Final[str] = "load"
_STAGE_RENDER: Final[str] = "render"
_STAGE_ENCODE: Final[str] = "encode"
_STAGE_STORE: Final[str] = "store"


class AnimateWorkflow:
    """Executes one animate job end to end."""

    async def __call__(self, context: JobExecutionContext) -> dict[str, Any]:
        """Render the animation described by the job payload."""
        payload = context.payload
        run_id = str(payload.get("run_id", ""))
        if not run_id:
            raise JobError(
                "The animate job payload is missing the run.", details={"reason": "missing_run"}
            )
        fps = int(payload.get("fps", 2))
        parameter_filter = payload.get("parameter_id")
        method_filter = payload.get("method")

        await self._progress(context, 0.05, _STAGE_LOAD)
        async with session_scope(context.session_factory) as session:
            runs = RunRepository(session)
            artifacts = ArtifactRepository(session)
            await runs.require(run_id)
            rows = await artifacts.list_for_run(run_id)

        rasters = [
            row
            for row in rows
            if row.kind == "raster"
            and (row.details or {}).get("kind") == "geotiff"
            and (
                parameter_filter is None
                or (row.details or {}).get("parameter_id") == parameter_filter
            )
            and (method_filter is None or (row.details or {}).get("method") == method_filter)
        ]
        if not rasters:
            raise NotFoundError(
                "The run has no stored rasters for the requested parameter and method.",
                details={"run_id": run_id, "parameter": parameter_filter, "method": method_filter},
            )
        rasters.sort(key=lambda row: str((row.details or {}).get("sampled_at", "")))
        if len(rasters) > MAX_ANIMATION_FRAMES:
            raise JobError(
                "The animation would exceed the maximum frame count.",
                details={"frames": len(rasters), "max": MAX_ANIMATION_FRAMES},
            )

        spec = AnimationSpec(fps=fps)
        frames_meta: list[dict[str, Any]] = []
        values_per_frame = []
        grid = None
        for row in rasters:
            await self._check_cancel(context)
            payload_bytes = context.object_store.get_bytes(row.storage_key)
            frame_grid, values = grid_from_geotiff(payload_bytes)
            grid = frame_grid if grid is None else grid
            values_per_frame.append(values)
            metadata = row.details or {}
            frames_meta.append(
                {
                    "timestamp": str(metadata.get("sampled_at")),
                    "status": "observed",
                    "artifact_id": row.id,
                }
            )
        if grid is None:
            raise JobError("No raster could be decoded.", details={"reason": "no_rasters"})

        scale = compute_scale(values_per_frame, policy=ScalePolicy.GLOBAL_SEQUENCE)
        palette = resolve_palette(str(payload.get("palette", "viridis")))
        unit = str((rasters[0].details or {}).get("unit", ""))
        method = str((rasters[0].details or {}).get("method", "unknown"))
        parameter_id = str((rasters[0].details or {}).get("parameter_id", "unknown"))

        await self._progress(context, 0.3, _STAGE_RENDER)
        from datetime import datetime

        frames = [
            AnimationFrame(
                timestamp=datetime.fromisoformat(meta["timestamp"]),
                status=FrameStatus(meta["status"]),
                png=b"",
            )
            for meta in frames_meta
        ]
        await self._check_cancel(context)
        await self._progress(context, 0.6, _STAGE_ENCODE)
        result = render_animation(
            frames,
            spec=spec,
            scale=scale,
            palette=palette,
            unit=unit,
            method=method,
            parameter_id=parameter_id,
            values_per_frame=values_per_frame,
            grid=grid,
        )

        await self._progress(context, 0.85, _STAGE_STORE)
        legend_png = render_legend_png(
            vmin=scale.vmin,
            vmax=scale.vmax,
            unit=unit,
            palette=palette,
            title=f"{parameter_id} ({unit})",
            frame_statuses=tuple(frame.status.value for frame in frames),
        )
        stored: list[dict[str, Any]] = [
            {
                "artifact_id": new_artifact_id(),
                "kind": "video",
                "sha256": result.sha256,
                "size_bytes": len(result.mp4),
                "content_type": "video/mp4",
                "storage_key": build_artifact_key(
                    "runs", result.sha256, f"animation-{parameter_id}-{method}.mp4"
                ),
                "run_id": run_id,
                "metadata": result.metadata,
                "payload": result.mp4,
            },
            {
                "artifact_id": new_artifact_id(),
                "kind": "other",
                "sha256": hashlib.sha256(metadata_json(result.metadata)).hexdigest(),
                "size_bytes": len(metadata_json(result.metadata)),
                "content_type": "application/json",
                "storage_key": build_artifact_key(
                    "runs",
                    hashlib.sha256(metadata_json(result.metadata)).hexdigest(),
                    "animation-metadata.json",
                ),
                "run_id": run_id,
                "metadata": {"kind": "video_metadata", "run_id": run_id},
                "payload": metadata_json(result.metadata),
            },
            {
                "artifact_id": new_artifact_id(),
                "kind": "figure",
                "sha256": hashlib.sha256(legend_png).hexdigest(),
                "size_bytes": len(legend_png),
                "content_type": "image/png",
                "storage_key": build_artifact_key(
                    "runs", hashlib.sha256(legend_png).hexdigest(), "animation-legend.png"
                ),
                "run_id": run_id,
                "metadata": {"kind": "legend", "run_id": run_id},
                "payload": legend_png,
            },
        ]
        for entry in stored:
            context.object_store.put_bytes(
                entry["storage_key"], entry["payload"], content_type=entry["content_type"]
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
                    run_id=run_id,
                    metadata=entry["metadata"],
                )
        await self._progress(context, 1.0, None)
        return {
            "run_id": run_id,
            "video_artifact_id": stored[0]["artifact_id"],
            "frame_count": result.frame_count,
            "fps": result.fps,
            "duration_seconds": result.duration_seconds,
            "sha256": result.sha256,
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


def register_animate_handler(registry: JobHandlerRegistry) -> None:
    """Register the animate handler on a workflow registry."""
    registry.register(JobType.ANIMATE, AnimateWorkflow())
