from __future__ import annotations

import asyncio
import base64
import logging
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import matplotlib
import pandas as pd
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from config import settings
from db import init_db
from routes.animation_api import router as animation_router
from routes.data_api import router as data_router
from utils.data_processing import DataValidationError, normalize_observations, ordered_timestamps, read_tabular_file
from utils.datasets import build_dataset_payload, demo_stored_name, secure_filename, stored_upload_name
from utils.jobs import run_science_job
from utils.security import (
    CHALLENGE_HEADER_VALUE,
    AuthPathMiddleware,
    BodyLimitMiddleware,
    RequestBodyTooLarge,
    SecurityHeadersMiddleware,
    require_auth,
)
from utils.spatial_rendering import (
    SpatialRenderingError,
    interpolate_surface,
    load_boundary,
    render_colorbar_png,
    render_surface_png,
)
from utils.storage import purge_expired_files, remove_replaced_upload

matplotlib.use("Agg")
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

ROOT = settings.root
UPLOAD_DIR = ROOT / "uploads"
BOUNDARY_UPLOAD_DIR = ROOT / "static" / "data" / "uploads"
DEFAULT_BOUNDARY = ROOT / "static" / "data" / "export.geojson"
ALLOWED_EXTENSIONS = {"csv", "xlsx", "xls"}
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
BOUNDARY_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
templates = Jinja2Templates(directory=str(ROOT / "templates"))


@asynccontextmanager
async def lifespan(_application: FastAPI):
    removed = await asyncio.to_thread(
        purge_expired_files,
        (UPLOAD_DIR, BOUNDARY_UPLOAD_DIR),
        settings.upload_ttl_hours,
    )
    if removed:
        logger.info("Startup sweep removed %d expired upload file(s).", removed)
    await init_db()
    yield


app = FastAPI(
    title="Trendsmapp Prototype API",
    version="1.0.0",
    description="Validated spatial visualization and temporal animation prototype.",
    lifespan=lifespan,
)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    same_site="lax",
    https_only=settings.https_only,
)
# Middleware order below (innermost to outermost): session, body cap, auth,
# security headers. Auth therefore rejects unauthenticated requests before any
# body bytes are parsed, and hardening headers wrap every response.
app.add_middleware(AuthPathMiddleware, protected_prefixes=("/static/data/uploads",))
app.add_middleware(BodyLimitMiddleware, maximum_bytes=settings.max_upload_bytes)
app.add_middleware(SecurityHeadersMiddleware)
app.include_router(data_router)
app.include_router(animation_router)


def _allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


async def _save_upload(upload: UploadFile, destination: Path, maximum_bytes: int) -> None:
    written = 0
    try:
        with destination.open("wb") as output:
            while chunk := await upload.read(1024 * 1024):
                written += len(chunk)
                if written > maximum_bytes:
                    raise DataValidationError(
                        f"The upload exceeds the {maximum_bytes / (1024 * 1024):.0f} MiB limit."
                    )
                output.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()


def _resolve_boundary_path(value: str | None) -> Path:
    if not value or value in {"static/data/export.geojson", "/static/data/export.geojson"}:
        return DEFAULT_BOUNDARY
    relative = value.lstrip("/\\").replace("/", os.sep)
    candidate = (ROOT / relative).resolve()
    allowed_root = BOUNDARY_UPLOAD_DIR.resolve()
    if candidate != allowed_root and allowed_root not in candidate.parents:
        raise SpatialRenderingError("Boundary path is outside the permitted upload directory.")
    if not candidate.is_file():
        raise SpatialRenderingError("Boundary file does not exist.")
    return candidate


def _dataset_payload(path: Path, stored_name: str, original_name: str) -> dict:
    observations = normalize_observations(read_tabular_file(path))
    return build_dataset_payload(observations, stored_name, original_name)


def _render_heatmap_payload(payload: dict) -> dict:
    if not isinstance(payload.get("data"), list):
        raise DataValidationError("A JSON observation array is required.")
    observations = normalize_observations(pd.DataFrame(payload["data"]))
    if len(observations) > settings.max_processed_rows:
        raise DataValidationError(
            f"The prototype supports at most {settings.max_processed_rows:,} normalized observations per request."
        )
    available_parameters = observations["parameter"].drop_duplicates().tolist()
    requested_parameter = str(payload.get("parameter", "")).strip()
    if len(available_parameters) > 1:
        if not requested_parameter:
            raise DataValidationError(
                "The request contains multiple parameters; pass 'parameter' to select exactly one. Found: "
                + ", ".join(sorted(available_parameters))
            )
        if requested_parameter not in available_parameters:
            raise DataValidationError(
                f"Unknown parameter '{requested_parameter}'. "
                f"Available parameters: {', '.join(sorted(available_parameters))}"
            )
        observations = observations.loc[observations["parameter"] == requested_parameter].reset_index(drop=True)
        selected_parameter = requested_parameter
    else:
        selected_parameter = available_parameters[0]
    minimum = float(payload.get("global_min", observations["value"].min()))
    maximum = float(payload.get("global_max", observations["value"].max()))
    requested_raw = payload.get("timestamp_columns")
    if requested_raw is not None and not isinstance(requested_raw, list):
        raise DataValidationError("timestamp_columns must be an array of timestamp strings.")
    requested = requested_raw or ordered_timestamps(observations)
    parsed_requested = pd.to_datetime(pd.Series(requested), errors="coerce", utc=True, format="mixed")
    if parsed_requested.isna().any():
        raise DataValidationError("One or more requested timestamps are invalid.")
    timestamps = list(dict.fromkeys(parsed_requested.dt.strftime("%Y-%m-%dT%H:%M:%SZ").tolist()))
    if len(timestamps) > settings.max_timestamps:
        raise DataValidationError(f"The prototype supports at most {settings.max_timestamps} timestamps per request.")
    method = str(payload.get("method", "idw")).lower()
    if method not in {"idw", "kde"}:
        raise DataValidationError("Heatmap method must be 'idw' or 'kde'.")
    idw_power = max(0.1, min(float(payload.get("idw_power", 2.0)), 5.0))
    kde_bandwidth = max(0.1, min(float(payload.get("kde_bandwidth_km", 2.0)), 100.0))
    colormap = str(payload.get("colormap", "viridis"))
    boundary = load_boundary(_resolve_boundary_path(payload.get("boundary_path")))[0]

    images: dict[str, str] = {}
    for timestamp in timestamps:
        subset = observations.loc[observations["timestamp"] == timestamp]
        stations = subset[["latitude", "longitude"]].drop_duplicates()
        if len(stations) > settings.max_stations_per_frame:
            raise DataValidationError(
                f"Timestamp {timestamp} exceeds the {settings.max_stations_per_frame}-station limit."
            )
        if subset.empty:
            continue
        surface, extent, _ = interpolate_surface(
            subset["longitude"].to_numpy(float),
            subset["latitude"].to_numpy(float),
            subset["value"].to_numpy(float),
            boundary,
            method=method,
            resolution=settings.surface_resolution,
            power=idw_power,
            bandwidth_km=kde_bandwidth,
        )
        png = render_surface_png(surface, extent, minimum, maximum, colormap)
        images[timestamp] = base64.b64encode(png).decode("ascii")
    if not images:
        raise DataValidationError("No requested timestamps contained observations.")
    min_lon, min_lat, max_lon, max_lat = boundary.bounds
    return {
        "images": images,
        "bounds": [[min_lon, min_lat], [max_lon, max_lat]],
        "global_min": minimum,
        "global_max": maximum,
        "method": method,
        "parameter": selected_parameter,
        "method_parameters": {
            "idw_power": idw_power if method == "idw" else None,
            "kde_bandwidth_km": kde_bandwidth if method == "kde" else None,
        },
    }


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(_request: Request, exc: StarletteHTTPException):
    headers = {"WWW-Authenticate": CHALLENGE_HEADER_VALUE} if exc.status_code == 401 else None
    return JSONResponse(status_code=exc.status_code, content={"error": str(exc.detail)}, headers=headers)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_request: Request, exc: RequestValidationError):
    errors = [error.get("msg", "Invalid request") for error in exc.errors()]
    return JSONResponse(status_code=422, content={"error": "; ".join(errors)})


@app.get("/", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
async def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/api/config", dependencies=[Depends(require_auth)])
async def public_config() -> dict:
    return {
        "demo_mode": settings.demo_mode,
        "limits": {
            "upload_bytes": settings.max_upload_bytes,
            "observations": settings.max_processed_rows,
            "timestamps": settings.max_timestamps,
            "stations_per_frame": settings.max_stations_per_frame,
        },
        "spatial_methods": ["idw", "kde"],
        "client_gpu_criteria": {
            "required_api": "webgl2",
            "reject_major_performance_caveat": True,
            "required_for": ["interactive_map_canvas"],
            "gpu_absent_fallbacks": ["scientific_idw", "scientific_kde"],
        },
        "animation_pipelines": [
            {
                "id": "scientific_idw",
                "label": "Scientific IDW (server CPU)",
                "requires_client_gpu": False,
                "spatial_method": "idw",
                "temporal_method": "linear_surface_interpolation",
            },
            {
                "id": "scientific_kde",
                "label": "Scientific KDE kernel smoother (server CPU)",
                "requires_client_gpu": False,
                "spatial_method": "kde",
                "temporal_method": "linear_surface_interpolation",
            },
        ],
    }


@app.get("/api/demo", dependencies=[Depends(require_auth)])
async def load_demo(request: Request):
    if not settings.demo_mode:
        raise HTTPException(status_code=404, detail="Demo mode is disabled.")
    # The demo workbook is parsed in place; no copy is written to uploads/.
    # The animation route resolves the stable session marker back to the dataset file.
    stable_name = demo_stored_name()
    payload = await asyncio.to_thread(_dataset_payload, settings.demo_dataset, stable_name, settings.demo_dataset.name)
    request.session["uploaded_filename"] = stable_name
    payload["demo"] = True
    return payload


@app.get("/static/data/export.geojson")
async def serve_geojson():
    return FileResponse(DEFAULT_BOUNDARY, media_type="application/geo+json")


@app.post("/upload", dependencies=[Depends(require_auth)])
async def upload_data(request: Request, file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file was selected.")
    if not _allowed_file(file.filename):
        raise HTTPException(status_code=400, detail="File type not allowed. Upload CSV, XLSX, or XLS.")
    stored_name = stored_upload_name(file.filename)
    destination = UPLOAD_DIR / stored_name
    try:
        await _save_upload(file, destination, settings.max_upload_bytes)
        payload = await asyncio.to_thread(_dataset_payload, destination, stored_name, secure_filename(file.filename))
        remove_replaced_upload(request.session.get("uploaded_filename"), UPLOAD_DIR)
        request.session["uploaded_filename"] = stored_name
        return payload
    except DataValidationError as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RequestBodyTooLarge as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except Exception as exc:
        destination.unlink(missing_ok=True)
        logger.exception("Upload processing failed")
        raise HTTPException(status_code=500, detail="The uploaded file could not be processed.") from exc


@app.post("/generate-heatmap", dependencies=[Depends(require_auth)])
async def generate_heatmap(payload: dict):
    try:
        result = await asyncio.to_thread(lambda: run_science_job(_render_heatmap_payload, payload, job_type="surface"))
        return result
    except (DataValidationError, SpatialRenderingError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/upload-boundary", dependencies=[Depends(require_auth)])
async def upload_boundary(request: Request, file: UploadFile = File(...)):
    safe_name = secure_filename(file.filename or "")
    if Path(safe_name).suffix.lower() not in {".geojson", ".json"}:
        raise HTTPException(status_code=400, detail="Only GeoJSON or JSON boundary files are allowed.")
    stored_name = f"{uuid.uuid4().hex}_{safe_name}"
    destination = BOUNDARY_UPLOAD_DIR / stored_name
    try:
        await _save_upload(file, destination, min(settings.max_upload_bytes, 10 * 1024 * 1024))
        load_boundary(destination)[0]
        relative = destination.relative_to(ROOT).as_posix()
        remove_replaced_upload(request.session.get("boundary_geojson"), BOUNDARY_UPLOAD_DIR)
        request.session["boundary_geojson"] = relative
        return {"message": "Boundary uploaded.", "path": f"/{relative}"}
    except (DataValidationError, OSError, ValueError, SpatialRenderingError) as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RequestBodyTooLarge as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=413, detail=str(exc)) from exc


@app.get("/legend/{timestamp:path}.png", dependencies=[Depends(require_auth)])
async def serve_legend(
    timestamp: str,
    min: float = 0,
    max: float = 1,
    colormap: str = "viridis",
    orientation: str = "vertical",
):
    if orientation not in {"vertical", "horizontal"}:
        raise HTTPException(status_code=400, detail="Legend orientation must be 'vertical' or 'horizontal'.")
    try:
        png = await asyncio.to_thread(
            render_colorbar_png, min, max, colormap, horizontal=orientation == "horizontal"
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(content=png, media_type="image/png")


app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
