from __future__ import annotations

import re
import uuid
from pathlib import Path

import pandas as pd

from config import settings
from utils.data_processing import DataValidationError, ordered_timestamps

DEMO_MARKER_PREFIX = "__demo__"


def secure_filename(filename: str) -> str:
    name = Path(filename).name
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")


def stored_upload_name(filename: str) -> str:
    safe = secure_filename(filename)
    if not safe:
        raise DataValidationError("The uploaded filename is invalid.")
    return f"{uuid.uuid4().hex}_{safe}"


def demo_stored_name() -> str:
    """Stable session marker for the bundled demo dataset; never a real file in uploads/."""
    return f"{DEMO_MARKER_PREFIX}{settings.demo_dataset.name}"


def build_dataset_payload(observations: pd.DataFrame, stored_name: str, original_name: str) -> dict:
    """Envelope shared by file uploads and database exports."""
    observations = observations.reset_index(drop=True)
    total = len(observations)
    if total > settings.max_processed_rows:
        raise DataValidationError(
            f"The prototype supports at most {settings.max_processed_rows:,} normalized observations per dataset."
        )
    timestamps = ordered_timestamps(observations)
    if len(timestamps) > settings.max_timestamps:
        raise DataValidationError(f"The prototype supports at most {settings.max_timestamps} timestamps per dataset.")
    records = observations.where(pd.notnull(observations), None).to_dict(orient="records")
    return {
        "message": f"Successfully processed {len(records)} observations.",
        "data": records,
        "stats": {
            "total_points": len(records),
            "parameter_count": int(observations["parameter"].nunique()),
            "timestamps": timestamps,
        },
        "total_records": len(records),
        "global_min": float(observations["value"].min()),
        "global_max": float(observations["value"].max()),
        "timestamp_columns": timestamps,
        "filename": stored_name,
        "original_filename": original_name,
    }
