from __future__ import annotations

import asyncio
import io
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from config import settings
from utils.animation_generator import fetch_data_for_animation, generate_spatiotemporal_video
from utils.data_processing import DataValidationError
from utils.datasets import demo_stored_name
from utils.jobs import run_science_job
from utils.security import require_auth
from utils.spatial_rendering import SpatialRenderingError

router = APIRouter(dependencies=[Depends(require_auth)])
ROOT = Path(__file__).resolve().parents[1]
UPLOAD_DIR = (ROOT / "uploads").resolve()
BOUNDARY_DIR = (ROOT / "static" / "data" / "uploads").resolve()
DEFAULT_BOUNDARY = (ROOT / "static" / "data" / "export.geojson").resolve()
SCIENTIFIC_METHODS = {"idw", "kde"}


def _uploaded_file(filename: str, request: Request) -> Path:
    if not filename or filename != request.session.get("uploaded_filename"):
        raise DataValidationError("The uploaded data file is not available in this session.")
    if filename == demo_stored_name():
        if not settings.demo_mode:
            raise DataValidationError("The bundled demo dataset is disabled.")
        return settings.demo_dataset.resolve()
    candidate = (UPLOAD_DIR / Path(filename).name).resolve()
    if UPLOAD_DIR not in candidate.parents or not candidate.is_file():
        raise DataValidationError("The uploaded data file no longer exists.")
    return candidate


def _boundary_file(value: str | None) -> Path:
    if not value or value in {"static/data/export.geojson", "/static/data/export.geojson"}:
        return DEFAULT_BOUNDARY
    candidate = (ROOT / value.lstrip("/\\")).resolve()
    if BOUNDARY_DIR not in candidate.parents or not candidate.is_file():
        raise DataValidationError("The selected boundary is not available.")
    return candidate


@router.post("/api/animate")
async def handle_animation_request(payload: dict, request: Request):
    required = {"start_date", "end_date", "fps", "frames_per_transition", "filename"}
    missing = sorted(required.difference(payload))
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing required fields: {', '.join(missing)}")
    try:
        filename = str(payload["filename"])
        parameter = str(payload.get("parameter", "")).strip()
        fps = int(payload["fps"])
        transitions = int(payload["frames_per_transition"])
        colormap = str(payload.get("colormap", "viridis"))
        method = str(payload.get("method", "idw")).lower()
        if method not in SCIENTIFIC_METHODS:
            raise DataValidationError("Scientific animation method must be 'idw' or 'kde'.")
        idw_power = max(0.1, min(float(payload.get("idw_power", 2.0)), 5.0))
        kde_bandwidth = max(0.1, min(float(payload.get("kde_bandwidth_km", 2.0)), 100.0))
        if payload.get("temporal_method", "linear_surface_interpolation") != "linear_surface_interpolation":
            raise DataValidationError("Scientific animation temporal method must be linear_surface_interpolation.")
        data = await asyncio.to_thread(
            fetch_data_for_animation,
            parameter,
            str(payload["start_date"]),
            str(payload["end_date"]),
            _uploaded_file(filename, request),
        )
        video = await asyncio.to_thread(
            lambda: run_science_job(
                generate_spatiotemporal_video,
                data,
                fps,
                transitions,
                colormap,
                _boundary_file(payload.get("boundary_path")),
                method,
                idw_power,
                kde_bandwidth,
                job_type="video"
            )
        )
        safe_parameter = re.sub(r"[^A-Za-z0-9_-]+", "_", parameter or "parameter").strip("_")
        headers = {
            "Content-Disposition": (
                f'attachment; filename="{safe_parameter or "parameter"}_{method}_animation.mp4"'
            ),
            "X-Trendsmapp-Spatial-Method": method,
            "X-Trendsmapp-Temporal-Method": "linear_surface_interpolation",
            "X-Trendsmapp-Execution": "server_cpu",
            "X-Trendsmapp-Method-Parameter": (
                f"idw_power={idw_power}" if method == "idw" else f"kde_bandwidth_km={kde_bandwidth}"
            ),
        }
        return StreamingResponse(io.BytesIO(video), media_type="video/mp4", headers=headers)
    except (DataValidationError, SpatialRenderingError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Animation generation failed unexpectedly.") from exc
