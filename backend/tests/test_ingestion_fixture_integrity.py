"""Fixture integrity: the committed test data must match its recorded digests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

TESTDATA_DIRECTORY = Path(__file__).resolve().parents[1] / "testdata"
DIGESTS_PATH = TESTDATA_DIRECTORY / "digests.json"

REQUIRED_FIXTURES = (
    "long_observations.csv",
    "wide_station_matrix.csv",
    "observations.tsv",
    "no_header_table.csv",
    "cp1252_non_utf8.csv",
    "malformed_ragged.csv",
    "malformed_unclosed_quote.csv",
    "binary_disguised.csv",
    "empty.csv",
    "observations.xlsx",
    "formulas_cached.xlsx",
    "error_cells.xlsx",
    "not_a_workbook.xlsx",
    "observations.parquet",
    "nested_columns.parquet",
    "truncated.parquet",
)


def test_digest_manifest_exists() -> None:
    assert DIGESTS_PATH.exists(), "run backend/scripts/make_testdata.py once"


def test_every_required_fixture_is_recorded() -> None:
    recorded = json.loads(DIGESTS_PATH.read_text(encoding="utf-8"))
    missing = [name for name in REQUIRED_FIXTURES if name not in recorded]
    assert missing == []


def test_every_recorded_fixture_matches_its_digest() -> None:
    recorded = json.loads(DIGESTS_PATH.read_text(encoding="utf-8"))
    for name, digest in sorted(recorded.items()):
        path = TESTDATA_DIRECTORY / name
        assert path.exists(), f"{name} is missing from testdata"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, (
            f"{name} drifted from its recorded digest"
        )


def test_no_unrecorded_files_are_committed() -> None:
    recorded = json.loads(DIGESTS_PATH.read_text(encoding="utf-8"))
    for path in TESTDATA_DIRECTORY.iterdir():
        if path.name in {"digests.json", "README.md"}:
            continue
        assert path.name in recorded, f"{path.name} is not recorded in digests.json"


def test_long_fixture_carries_the_expected_scientific_cases() -> None:
    """The fixture documents the QC cases the normalization tests rely on."""
    content = (TESTDATA_DIRECTORY / "long_observations.csv").read_text(encoding="utf-8")
    assert "<0.01" in content, "the censored-value case is missing"
    assert "nan" in content, "the non-finite case is missing"
    assert "25.0" in content, "the out-of-range case is missing"
    assert content.count("\n") >= 13, "the fixture lost rows"
