"""Typed identifier constructors and validation.

Identifiers are opaque, prefixed, and derived from random bytes. Clients never
choose them, and the prefix makes an identifier self-describing in logs and
database columns without exposing any ordering or content information.
"""

from __future__ import annotations

import re
from typing import Final
from uuid import uuid4

from trendsmapp.errors import DomainError

__all__ = [
    "OBSERVATION_ID_PATTERN",
    "new_artifact_id",
    "new_dataset_id",
    "new_dataset_version_id",
    "new_export_id",
    "new_job_id",
    "new_observation_id",
    "new_parameter_id",
    "new_provenance_id",
    "new_report_id",
    "new_run_id",
    "new_station_id",
    "new_upload_id",
    "validate_identifier",
]

OBSERVATION_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"^obs_[0-9a-f]{32}$")

_PREFIXES: Final[dict[str, re.Pattern[str]]] = {
    "ds": re.compile(r"^ds_[0-9a-f]{32}$"),
    "dsv": re.compile(r"^dsv_[0-9a-f]{32}$"),
    "upl": re.compile(r"^upl_[0-9a-f]{32}$"),
    "job": re.compile(r"^job_[0-9a-f]{32}$"),
    "run": re.compile(r"^run_[0-9a-f]{32}$"),
    "obs": re.compile(r"^obs_[0-9a-f]{32}$"),
    "stn": re.compile(r"^stn_[0-9a-f]{32}$"),
    "par": re.compile(r"^par_[0-9a-f]{32}$"),
    "prv": re.compile(r"^prv_[0-9a-f]{32}$"),
    "art": re.compile(r"^art_[0-9a-f]{32}$"),
    "exp": re.compile(r"^exp_[0-9a-f]{32}$"),
    "rpt": re.compile(r"^rpt_[0-9a-f]{32}$"),
}


def _new_identifier(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def new_dataset_id() -> str:
    """Return a new dataset identifier."""
    return _new_identifier("ds")


def new_dataset_version_id() -> str:
    """Return a new dataset version identifier."""
    return _new_identifier("dsv")


def new_upload_id() -> str:
    """Return a new upload session identifier."""
    return _new_identifier("upl")


def new_job_id() -> str:
    """Return a new job identifier."""
    return _new_identifier("job")


def new_run_id() -> str:
    """Return a new analysis run identifier."""
    return _new_identifier("run")


def new_observation_id() -> str:
    """Return a new observation identifier."""
    return _new_identifier("obs")


def new_station_id() -> str:
    """Return a new station identifier."""
    return _new_identifier("stn")


def new_parameter_id() -> str:
    """Return a new parameter identifier."""
    return _new_identifier("par")


def new_provenance_id() -> str:
    """Return a new provenance identifier."""
    return _new_identifier("prv")


def new_artifact_id() -> str:
    """Return a new artifact identifier."""
    return _new_identifier("art")


def new_export_id() -> str:
    """Return a new export identifier."""
    return _new_identifier("exp")


def new_report_id() -> str:
    """Return a new report identifier."""
    return _new_identifier("rpt")


def validate_identifier(prefix: str, value: str) -> str:
    """Validate that ``value`` is a well-formed identifier for ``prefix``."""
    pattern = _PREFIXES.get(prefix)
    if pattern is None:
        raise DomainError(f"Unknown identifier prefix '{prefix}'.")
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise DomainError(
            f"'{value}' is not a valid '{prefix}' identifier.",
            details={"prefix": prefix, "value": value},
        )
    return value
