from __future__ import annotations

from pathlib import Path
from typing import Final
from zipfile import BadZipFile

import numpy as np
import pandas as pd

LATITUDE_ALIASES: Final = ("latitude", "lat", "y")
LONGITUDE_ALIASES: Final = ("longitude", "lon", "lng", "long", "x")
TIMESTAMP_ALIASES: Final = ("timestamp", "sampled_at", "date", "datetime", "time")
VALUE_ALIASES: Final = ("value", "count", "measurement", "result")
PARAMETER_ALIASES: Final = ("parameter", "species", "variable", "analyte")


class DataValidationError(ValueError):
    """Raised when an input cannot be converted without scientific ambiguity."""


def _find_column(columns: list[str], aliases: tuple[str, ...]) -> str | None:
    return next((name for name in aliases if name in columns), None)


def read_tabular_file(path: str | Path) -> pd.DataFrame:
    """Read a supported table and convert parser failures into safe validation errors.

    CSV content is parsed by pandas. XLSX uses OpenPyXL and legacy XLS uses xlrd,
    both selected by pandas from the extension. The function never attempts to
    infer a different format after a parser fails because that could reinterpret
    corrupted input as valid data.
    """
    source = Path(path)
    suffix = source.suffix.lower()
    try:
        if suffix == ".csv":
            return pd.read_csv(source)
        if suffix in {".xlsx", ".xls"}:
            return pd.read_excel(source)
        raise DataValidationError(f"Unsupported file type: {suffix or 'unknown'}")
    except DataValidationError:
        raise
    except (BadZipFile, ImportError, OSError, UnicodeDecodeError, ValueError, pd.errors.ParserError) as exc:
        raise DataValidationError(
            f"The {suffix.lstrip('.').upper() or 'uploaded'} file is corrupted or cannot be parsed."
        ) from exc


def _canonical_timestamps(values: pd.Series) -> pd.Series:
    text = values.astype(str).str.strip()
    parsed = pd.to_datetime(text, errors="coerce", utc=True, format="mixed")
    invalid = parsed.isna()
    if invalid.any():
        examples = ", ".join(text.loc[invalid].drop_duplicates().head(3).tolist())
        raise DataValidationError(
            f"Found {int(invalid.sum())} invalid timestamp value(s). Examples: {examples or 'blank'}"
        )
    return parsed.dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_observations(raw: pd.DataFrame) -> pd.DataFrame:
    """Convert an explicit long or wide table to validated observation records.

    Long tables require latitude, longitude, timestamp, and value roles. Wide
    tables require latitude and longitude plus timestamp-labelled measurement
    columns. Coordinate aliases are accepted, but positional guessing is not.
    Blank wide measurements are treated as unsampled combinations; malformed
    non-blank coordinates, values, and timestamps reject the entire upload.
    """
    if raw.empty:
        raise DataValidationError("The uploaded table is empty.")

    frame = raw.copy()
    frame.columns = [str(column).strip().lower() for column in frame.columns]
    columns = list(frame.columns)
    if len(columns) != len(set(columns)):
        raise DataValidationError("Column names must be unique after trimming and case normalization.")
    latitude = _find_column(columns, LATITUDE_ALIASES)
    longitude = _find_column(columns, LONGITUDE_ALIASES)
    if latitude is None or longitude is None:
        raise DataValidationError("Missing required latitude and longitude columns.")

    timestamp = _find_column(columns, TIMESTAMP_ALIASES)
    value = _find_column(columns, VALUE_ALIASES)
    parameter = _find_column(columns, PARAMETER_ALIASES)
    if bool(timestamp) != bool(value):
        raise DataValidationError("Long-format input must provide both timestamp and value columns.")

    if timestamp and value:
        selected = frame.rename(
            columns={latitude: "latitude", longitude: "longitude", timestamp: "timestamp", value: "value"}
        )
        selected["parameter"] = selected[parameter] if parameter else "UploadedParameter"
        observations = selected[["latitude", "longitude", "timestamp", "value", "parameter"]].copy()
    else:
        metadata = {latitude, longitude}
        if parameter:
            metadata.add(parameter)
        measurement_columns = [column for column in columns if column not in metadata]
        if not measurement_columns:
            raise DataValidationError("No timestamp measurement columns were found.")
        _canonical_timestamps(pd.Series(measurement_columns, dtype="object"))
        observations = frame.melt(
            id_vars=list(metadata),
            value_vars=measurement_columns,
            var_name="timestamp",
            value_name="value",
        ).rename(columns={latitude: "latitude", longitude: "longitude"})
        observations["parameter"] = observations[parameter] if parameter else "UploadedParameter"

    numeric_latitude = pd.to_numeric(observations["latitude"], errors="coerce")
    numeric_longitude = pd.to_numeric(observations["longitude"], errors="coerce")
    invalid_coordinates = (
        ~np.isfinite(numeric_latitude)
        | ~np.isfinite(numeric_longitude)
        | ~numeric_latitude.between(-90, 90)
        | ~numeric_longitude.between(-180, 180)
    )
    if invalid_coordinates.any():
        raise DataValidationError(f"Found {int(invalid_coordinates.sum())} row(s) with invalid coordinates.")

    blank_values = observations["value"].isna() | observations["value"].astype(str).str.strip().eq("")
    numeric_values = pd.to_numeric(observations["value"], errors="coerce")
    malformed_values = ~blank_values & (~np.isfinite(numeric_values))
    if malformed_values.any():
        count = int(malformed_values.sum())
        raise DataValidationError(f"Found {count} non-numeric or non-finite measurement value(s).")
    observations = observations.loc[~blank_values].copy()
    if observations.empty:
        raise DataValidationError("The uploaded table contains no measured values.")

    observations["latitude"] = numeric_latitude.loc[observations.index]
    observations["longitude"] = numeric_longitude.loc[observations.index]
    observations["value"] = numeric_values.loc[observations.index]
    observations["timestamp"] = _canonical_timestamps(observations["timestamp"])
    observations["parameter"] = observations["parameter"].fillna("UploadedParameter").astype(str).str.strip()
    observations.loc[observations["parameter"].eq(""), "parameter"] = "UploadedParameter"
    observations["species"] = observations["parameter"]
    return observations.reset_index(drop=True)


def ordered_timestamps(observations: pd.DataFrame) -> list[str]:
    """Return unique canonical timestamps in chronological order."""
    values = observations["timestamp"].drop_duplicates().astype(str).tolist()
    return sorted(values, key=pd.Timestamp)


def filter_date_range(observations: pd.DataFrame, start_date: str, end_date: str) -> pd.DataFrame:
    """Select observations inside an inclusive UTC range for animation."""
    parsed = pd.to_datetime(observations["timestamp"], errors="coerce", utc=True)
    start = pd.to_datetime(start_date, errors="coerce", utc=True)
    end = pd.to_datetime(end_date, errors="coerce", utc=True)
    if pd.isna(start) or pd.isna(end) or start > end:
        raise DataValidationError("The animation date range is invalid.")
    result = observations.loc[parsed.between(start, end)].copy()
    result["sampled_at"] = parsed.loc[result.index]
    return result.reset_index(drop=True)
