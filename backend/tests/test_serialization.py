"""Tests for canonical JSON serialization."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from uuid import UUID

import pytest

from trendsmapp.serialization import (
    canonical_json,
    canonical_json_bytes,
    normalize_for_canonical,
    read_json,
    write_canonical_json,
)


class _Colour(StrEnum):
    GREEN = "green"


def test_canonical_json_sorts_keys_and_removes_whitespace() -> None:
    payload = {"b": 1, "a": 2}
    assert canonical_json(payload) == '{"a":2,"b":1}'


def test_canonical_json_normalizes_integral_floats() -> None:
    assert canonical_json({"value": 2.0}) == '{"value":2}'


def test_canonical_json_keeps_fractional_floats() -> None:
    assert canonical_json({"value": 2.5}) == '{"value":2.5}'


def test_canonical_json_rejects_non_finite_numbers() -> None:
    with pytest.raises(ValueError, match="finite"):
        canonical_json({"value": float("inf")})
    with pytest.raises(ValueError, match="finite"):
        canonical_json({"value": float("nan")})


def test_canonical_json_encodes_datetimes_as_utc() -> None:
    moment = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    assert canonical_json({"at": moment}) == '{"at":"2026-01-02T03:04:05Z"}'


def test_canonical_json_encodes_decimals_uuids_and_enums() -> None:
    identifier = UUID("00000000-0000-0000-0000-000000000001")
    assert canonical_json({"id": identifier}) == f'{{"id":"{identifier}"}}'
    assert canonical_json({"colour": _Colour.GREEN}) == '{"colour":"green"}'
    assert canonical_json({"amount": Decimal("2.00")}) == '{"amount":2}'


def test_canonical_json_sorts_sets_deterministically() -> None:
    assert canonical_json({"items": {"b", "a"}}) == '{"items":["a","b"]}'


def test_canonical_json_rejects_unknown_types() -> None:
    with pytest.raises(TypeError):
        canonical_json({"value": object()})


def test_normalize_for_canonical_handles_nested_sequences() -> None:
    normalized = normalize_for_canonical({"rows": [(1, 2), (3, 4)]})
    assert normalized == {"rows": [[1, 2], [3, 4]]}


def test_write_canonical_json_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    written = write_canonical_json(path, {"b": 2, "a": 1})
    assert path.read_bytes() == written
    assert read_json(path) == {"a": 1, "b": 2}
    assert json.loads(written.decode("utf-8")) == {"a": 1, "b": 2}


def test_canonical_json_bytes_are_utf8() -> None:
    assert canonical_json_bytes({"label": "Chilika"}) == b'{"label":"Chilika"}'
