from __future__ import annotations

import asyncio
import logging
import math
import uuid
from datetime import datetime
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from db import Measurement, Parameter, Station, get_db_session
from utils.data_processing import DataValidationError, normalize_observations
from utils.datasets import build_dataset_payload
from utils.security import require_auth
from utils.storage import remove_replaced_upload

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(require_auth)])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "templates"))
ROOT = Path(__file__).resolve().parents[1]
UPLOAD_DIR = (ROOT / "uploads").resolve()


@router.get("/data-entry", response_class=HTMLResponse)
async def data_entry_page(request: Request):
    return templates.TemplateResponse(request=request, name="data-entry.html")


@router.get("/api/parameters")
async def list_parameters() -> list[str]:
    try:
        async with get_db_session() as database_session:
            result = await database_session.execute(select(Parameter.name).order_by(Parameter.name))
            return list(result.scalars())
    except Exception as exc:
        logger.exception("Failed to fetch parameters")
        raise HTTPException(status_code=500, detail="Failed to fetch parameters.") from exc


@router.post("/api/parameters", status_code=status.HTTP_201_CREATED)
async def add_parameter(payload: dict) -> dict:
    name = str(payload.get("name", "")).strip()
    if not name:
        raise HTTPException(status_code=400, detail="Parameter name is required.")
    try:
        async with get_db_session() as database_session:
            database_session.add(Parameter(name=name))
        return {"status": "success", "name": name}
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Parameter already exists.") from exc


@router.get("/api/timestamps")
async def list_timestamps() -> list[str]:
    try:
        async with get_db_session() as database_session:
            result = await database_session.execute(
                select(Measurement.sampled_at).distinct().order_by(Measurement.sampled_at)
            )
            return [value.isoformat() for value in result.scalars()]
    except Exception as exc:
        logger.exception("Failed to fetch timestamps")
        raise HTTPException(status_code=500, detail="Failed to fetch timestamps.") from exc


def _pivot_measurements(frame: pd.DataFrame) -> pd.DataFrame:
    """Pivot normalized measurement rows; refuse to collapse conflicting duplicates."""
    duplicates = frame.duplicated(subset=["station_id", "param_date"], keep=False)
    if bool(duplicates.any()):
        examples = frame.loc[duplicates, ["station_id", "param_date", "value"]].head(5).to_dict(orient="records")
        raise ValueError(
            "Duplicate measurements for the same station, parameter, and date violate the storage "
            f"uniqueness contract. Refusing to collapse them silently. Examples: {examples}"
        )
    return frame.pivot_table(
        index=["station_id", "latitude", "longitude"], columns="param_date", values="value", aggfunc="first"
    ).reset_index()


@router.get("/api/table")
async def get_table() -> list[dict]:
    try:
        async with get_db_session() as database_session:
            result = await database_session.execute(
                select(
                    Station.id,
                    Station.latitude,
                    Station.longitude,
                    Parameter.name,
                    Measurement.sampled_at,
                    Measurement.value,
                )
                .select_from(Measurement)
                .join(Station, Measurement.station_id == Station.id)
                .join(Parameter, Measurement.parameter_id == Parameter.id)
            )
            rows = result.all()
        if not rows:
            return []
        frame = pd.DataFrame(rows, columns=["station_id", "latitude", "longitude", "parameter", "sampled_at", "value"])
        frame["param_date"] = frame["parameter"] + "_" + pd.to_datetime(frame["sampled_at"]).dt.strftime("%Y-%m-%d")
        pivoted = _pivot_measurements(frame)
        return pivoted.where(pd.notnull(pivoted), None).to_dict(orient="records")
    except ValueError as exc:
        # Duplicate measurement constraint violation - return 409 Conflict with details
        error_msg = str(exc)
        if "Duplicate measurements" in error_msg and "Examples:" in error_msg:
            # Extract examples from error message for structured response
            logger.warning("Data-entry pivot rejected conflicting data: %s", error_msg)
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "duplicate_measurements",
                    "message": "Duplicate measurements found for the same station, parameter, and date.",
                    "detail": error_msg
                }
            ) from exc
        else:
            logger.error("Data-entry validation error: %s", error_msg)
            raise HTTPException(status_code=400, detail=error_msg) from exc
    except Exception as exc:
        logger.exception("Failed to fetch data-entry table")
        raise HTTPException(status_code=500, detail="Failed to fetch table data.") from exc


def _validated_rows(payload: object) -> list[dict]:
    if not isinstance(payload, list):
        raise ValueError("Expected an array of measurement rows.")
    validated = []
    for index, row in enumerate(payload):
        if not isinstance(row, dict):
            raise ValueError(f"Row {index + 1} is not an object.")
        try:
            latitude = float(row["latitude"])
            longitude = float(row["longitude"])
            parameter = str(row["parameter"]).strip()
            timestamp_value = row.get("sampled_at", row.get("timestamp"))
            sampled_at = datetime.fromisoformat(str(timestamp_value).replace("Z", "+00:00")).date()
            value = None if row.get("value") in {None, ""} else float(row["value"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Row {index + 1} is invalid: {exc}") from exc
        if (
            not math.isfinite(latitude)
            or not math.isfinite(longitude)
            or (value is not None and not math.isfinite(value))
            or not (-90 <= latitude <= 90 and -180 <= longitude <= 180)
            or not parameter
        ):
            raise ValueError(f"Row {index + 1} has invalid coordinates or parameter.")
        validated.append({
            "latitude": latitude,
            "longitude": longitude,
            "parameter": parameter,
            "sampled_at": sampled_at,
            "value": value,
        })
    return validated


@router.post("/api/table")
async def post_table(payload: list[dict]) -> dict:
    try:
        rows = _validated_rows(payload)
        async with get_db_session() as database_session:
            parameters = {item.name: item for item in (await database_session.execute(select(Parameter))).scalars()}
            stations = {
                (item.latitude, item.longitude): item
                for item in (await database_session.execute(select(Station))).scalars()
            }
            for row in rows:
                parameter = parameters.get(row["parameter"])
                if parameter is None:
                    parameter = Parameter(name=row["parameter"])
                    database_session.add(parameter)
                    await database_session.flush()
                    parameters[parameter.name] = parameter
                key = (row["latitude"], row["longitude"])
                station = stations.get(key)
                if station is None:
                    station = Station(latitude=row["latitude"], longitude=row["longitude"])
                    database_session.add(station)
                    await database_session.flush()
                    stations[key] = station
                measurement = (
                    await database_session.execute(
                        select(Measurement).where(
                            Measurement.station_id == station.id,
                            Measurement.parameter_id == parameter.id,
                            Measurement.sampled_at == row["sampled_at"],
                        )
                    )
                ).scalar_one_or_none()
                if measurement is None:
                    database_session.add(Measurement(
                        station_id=station.id,
                        parameter_id=parameter.id,
                        sampled_at=row["sampled_at"],
                        value=row["value"],
                    ))
                else:
                    measurement.value = row["value"]
        return {"status": "success", "rows_processed": len(rows), "total_rows": len(rows)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to save table data")
        raise HTTPException(status_code=500, detail="Failed to save table data.") from exc


@router.delete("/api/measurement")
async def delete_measurement(payload: dict) -> dict:
    try:
        latitude = float(payload["latitude"])
        longitude = float(payload["longitude"])
        parameter_name = str(payload["parameter"])
        sampled_at = datetime.fromisoformat(str(payload["timestamp"]).replace("Z", "+00:00")).date()
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid measurement identifier.") from exc

    async with get_db_session() as database_session:
        measurement = (
            await database_session.execute(
                select(Measurement)
                .join(Station)
                .join(Parameter)
                .where(
                    Station.latitude == latitude,
                    Station.longitude == longitude,
                    Parameter.name == parameter_name,
                    Measurement.sampled_at == sampled_at,
                )
            )
        ).scalar_one_or_none()
        if measurement is None:
            raise HTTPException(status_code=404, detail="Measurement not found.")
        await database_session.delete(measurement)
    return {"status": "success"}


@router.post("/api/table/delete-station")
async def delete_station(payload: dict) -> dict:
    """Delete a coordinate row and every measurement recorded at that location."""
    try:
        latitude = float(payload["latitude"])
        longitude = float(payload["longitude"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Valid latitude and longitude are required.") from exc

    async with get_db_session() as database_session:
        station = (
            await database_session.execute(
                select(Station).where(Station.latitude == latitude, Station.longitude == longitude)
            )
        ).scalar_one_or_none()
        if station is None:
            raise HTTPException(status_code=404, detail="Station not found.")
        await database_session.execute(delete(Measurement).where(Measurement.station_id == station.id))
        await database_session.delete(station)
    return {"status": "success"}


@router.post("/api/export-dataset")
async def export_database_dataset(request: Request) -> dict:
    """Materialize saved database measurements as a session dataset for the science plane."""
    try:
        async with get_db_session() as database_session:
            result = await database_session.execute(
                select(
                    Station.latitude,
                    Station.longitude,
                    Parameter.name,
                    Measurement.sampled_at,
                    Measurement.value,
                )
                .select_from(Measurement)
                .join(Station, Measurement.station_id == Station.id)
                .join(Parameter, Measurement.parameter_id == Parameter.id)
                .order_by(Parameter.name, Measurement.sampled_at)
            )
            rows = result.all()
        if not rows:
            raise DataValidationError("The database contains no measurements to export.")
        frame = pd.DataFrame(rows, columns=["latitude", "longitude", "parameter", "sampled_at", "value"])
        frame["timestamp"] = pd.to_datetime(frame.pop("sampled_at")).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        observations = normalize_observations(frame[["latitude", "longitude", "timestamp", "value", "parameter"]])
        payload = build_dataset_payload(observations, "", "database_export.csv")

        stored_name = f"{uuid.uuid4().hex}_database_export.csv"
        destination = UPLOAD_DIR / stored_name
        try:
            await asyncio.to_thread(observations.to_csv, destination, index=False)
        except OSError as exc:
            logger.exception("Failed to write database export")
            raise HTTPException(status_code=500, detail="Failed to write the database export.") from exc

        remove_replaced_upload(request.session.get("uploaded_filename"), UPLOAD_DIR)
        request.session["uploaded_filename"] = stored_name
        payload["filename"] = stored_name
        payload["message"] = f"Exported {payload['total_records']} saved measurements for mapping."
        return payload
    except DataValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _validated_series_request(payload: object) -> tuple[str, object]:
    if not isinstance(payload, dict):
        raise ValueError("Expected a JSON object.")
    parameter_name = str(payload.get("parameter", "")).strip()
    if not parameter_name:
        raise ValueError("Parameter name is required.")
    timestamp_raw = payload.get("timestamp")
    if timestamp_raw in {None, ""}:
        return parameter_name, None
    try:
        sampled_at = datetime.fromisoformat(str(timestamp_raw).replace("Z", "+00:00")).date()
    except (TypeError, ValueError) as exc:
        raise ValueError("The timestamp must be an ISO date.") from exc
    return parameter_name, sampled_at


@router.post("/api/table/rename-timestamp")
async def rename_timestamp(payload: dict) -> dict:
    """Move a parameter/date series to a new date (optionally across every parameter)."""
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Expected a JSON object.")
    old_raw = str(payload.get("old_timestamp", "")).strip()
    new_raw = str(payload.get("new_timestamp", "")).strip()
    if not old_raw or not new_raw:
        raise HTTPException(status_code=400, detail="Both old_timestamp and new_timestamp are required.")
    if old_raw == new_raw:
        raise HTTPException(status_code=400, detail="The new timestamp must differ from the current one.")
    try:
        old_date = datetime.fromisoformat(old_raw.replace("Z", "+00:00")).date()
        new_date = datetime.fromisoformat(new_raw.replace("Z", "+00:00")).date()
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Timestamps must be ISO dates (YYYY-MM-DD).") from exc
    allow_missing = bool(payload.get("allow_missing", False))
    parameter_name = str(payload.get("parameter") or "").strip() or None
    try:
        async with get_db_session() as database_session:
            statement = update(Measurement).where(Measurement.sampled_at == old_date)
            if parameter_name is not None:
                statement = statement.where(
                    Measurement.parameter_id.in_(select(Parameter.id).where(Parameter.name == parameter_name))
                )
            result = await database_session.execute(statement.values(sampled_at=new_date))
            moved = int(result.rowcount or 0)
            if moved == 0 and not allow_missing:
                raise HTTPException(status_code=404, detail="No matching measurements were found.")
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail="A measurement already exists for that station, parameter, and target date.",
        ) from exc
    return {"status": "success", "moved": moved}


@router.post("/api/table/delete-series")
async def delete_series(payload: dict) -> dict:
    """Delete one parameter/date series across all stations, or the whole parameter when no date is given."""
    try:
        parameter_name, sampled_at = _validated_series_request(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        async with get_db_session() as database_session:
            statement = delete(Measurement).where(
                Measurement.parameter_id.in_(select(Parameter.id).where(Parameter.name == parameter_name))
            )
            if sampled_at is not None:
                statement = statement.where(Measurement.sampled_at == sampled_at)
            result = await database_session.execute(statement)
            deleted = int(result.rowcount or 0)
            if deleted == 0:
                raise HTTPException(status_code=404, detail="No matching measurements were found.")
            if sampled_at is None:
                # Remove the now-empty parameter row; measurements are already gone.
                await database_session.execute(delete(Parameter).where(Parameter.name == parameter_name))
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="The series could not be deleted safely.") from exc
    return {"status": "success", "deleted": deleted}


@router.post("/api/table/rename-parameter")
async def rename_parameter(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Expected a JSON object.")
    old_name = str(payload.get("old_name", "")).strip()
    new_name = str(payload.get("new_name", "")).strip()
    if not old_name or not new_name:
        raise HTTPException(status_code=400, detail="Both old_name and new_name are required.")
    if old_name == new_name:
        return {"status": "success", "renamed": False}
    try:
        async with get_db_session() as database_session:
            current = (
                await database_session.execute(select(Parameter).where(Parameter.name == old_name))
            ).scalar_one_or_none()
            if current is None:
                raise HTTPException(status_code=404, detail=f"Parameter '{old_name}' does not exist.")
            clash_id = (
                await database_session.execute(select(Parameter.id).where(Parameter.name == new_name))
            ).scalar_one_or_none()
            if clash_id is not None:
                raise HTTPException(status_code=409, detail=f"Parameter '{new_name}' already exists.")
            current.name = new_name
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="The parameter could not be renamed safely.") from exc
    return {"status": "success", "renamed": True}
