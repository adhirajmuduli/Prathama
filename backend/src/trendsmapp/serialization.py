"""Canonical JSON and deterministic manifest serialization.

Canonical JSON is the serialization used for every hash in the system: recipe
hashes, run manifests, artifact metadata, and the checksums embedded in export
bundles. Its rules are fixed:

* UTF-8 output without a byte order mark;
* object keys sorted by Unicode code point;
* no insignificant whitespace;
* finite numbers only, with integral floats normalized to integers;
* explicit ``null`` preserved where the contract makes it meaningful.

Two structurally equal documents therefore always produce identical bytes,
regardless of key insertion order or the Python types used to build them.
"""

from __future__ import annotations

import base64
import json
import math
from collections.abc import Mapping, Sequence, Set
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from trendsmapp.clock import isoformat_z

__all__ = [
    "canonical_json",
    "canonical_json_bytes",
    "normalize_for_canonical",
    "read_json",
    "write_canonical_json",
]

_SEPARATORS = (",", ":")


def _normalize_number(value: float) -> int | float:
    if math.isnan(value) or math.isinf(value):
        raise ValueError("Canonical JSON does not permit non-finite numbers.")
    if value.is_integer() and abs(value) < 2**53:
        return int(value)
    return value


def normalize_for_canonical(value: Any) -> Any:
    """Convert ``value`` into the canonical JSON data model.

    Mappings, sequences, and sets become plain JSON containers; datetimes,
    dates, decimals, UUIDs, enums, dataclasses, and Pydantic models become
    their canonical primitive representation. Unknown types raise
    :class:`TypeError` so that a serialization change cannot slip through
    unnoticed.
    """
    primitive = _normalize_primitive(value)
    if primitive is not _NOT_PRIMITIVE:
        return primitive
    if isinstance(value, Mapping):
        return {str(key): normalize_for_canonical(item) for key, item in value.items()}
    if isinstance(value, Set):
        normalized = [normalize_for_canonical(item) for item in value]
        return sorted(normalized, key=canonical_json)
    if isinstance(value, Sequence):
        return [normalize_for_canonical(item) for item in value]
    raise TypeError(f"Object of type {type(value).__name__} is not canonically serializable.")


class _NotPrimitive:
    """Sentinel: the value is not a primitive the scalar normalizer handles."""


_NOT_PRIMITIVE = _NotPrimitive()


def _normalize_primitive(value: Any) -> Any:
    """Normalize one scalar value, or return ``_NOT_PRIMITIVE`` for containers."""
    if value is None or isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, float):
        return _normalize_number(value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Canonical JSON does not permit non-finite decimals.")
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, datetime):
        return isoformat_z(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return normalize_for_canonical(value.value)
    if isinstance(value, BaseModel):
        return normalize_for_canonical(value.model_dump(mode="json"))
    if is_dataclass(value) and not isinstance(value, type):
        return normalize_for_canonical(asdict(value))
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    return _NOT_PRIMITIVE


def canonical_json(value: Any) -> str:
    """Return the canonical JSON text for ``value``."""
    return json.dumps(
        normalize_for_canonical(value),
        sort_keys=True,
        separators=_SEPARATORS,
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_json_bytes(value: Any) -> bytes:
    """Return the canonical UTF-8 JSON bytes for ``value``."""
    return canonical_json(value).encode("utf-8")


def write_canonical_json(path: Path, value: Any) -> bytes:
    """Write ``value`` to ``path`` as canonical JSON and return the bytes written."""
    payload = canonical_json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return payload


def read_json(path: Path) -> Any:
    """Read a JSON document from ``path``."""
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)
