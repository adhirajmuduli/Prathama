"""Regenerate the deterministic ingestion fixtures under ``backend/testdata``.

Every fixture is synthetic and byte-deterministic. Text fixtures are written
with LF newlines and UTF-8 (except the Windows-1252 fixture, which exists to
exercise encoding fallback). The workbook fixtures are normalized after
generation so that their ZIP members carry a fixed timestamp, which makes two
runs of this script produce identical bytes, and the Parquet fixture is written
by PyArrow, which is byte-deterministic for identical input.

The digest of every fixture is recorded in ``testdata/digests.json``. A test
asserts that the committed files still match those digests, so a fixture can
never drift silently from the behavior the tests describe.

Usage::

    python scripts/make_testdata.py            # regenerate and print digests
    python scripts/make_testdata.py --check    # verify the committed digests
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import zipfile
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import openpyxl
import pyarrow as pa
import pyarrow.parquet as pq

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TESTDATA_DIRECTORY = Path(__file__).resolve().parents[1] / "testdata"
DIGESTS_PATH = TESTDATA_DIRECTORY / "digests.json"

#: The fixed timestamp written into every ZIP member of a workbook fixture.
FIXED_ZIP_TIMESTAMP = (2020, 1, 1, 0, 0, 0)

_LONG_CSV = """station,latitude,longitude,sampled_at,parameter,value,unit,qualifier,depth_m,notes
St. A,19.7350,85.4700,2024-01-15T09:30:00Z,dissolved_oxygen,6.8,mg/L,,0.5,
St. A,19.7350,85.4700,2024-01-15T09:30:00Z,salinity,12.4,psu,,0.5,
St. B,19.8100,85.5200,2024-01-15T10:05:00Z,dissolved_oxygen,<0.01,mg/L,below_detection_limit,1.0,calibrated on site
St. B,19.8100,85.5200,2024-01-15T10:05:00Z,salinity,,psu,,1.0,
St. A,19.7350,85.4700,2024-02-12T09:15:00Z,dissolved_oxygen,25.0,mg/L,,0.5,flagged by the range check
St. A,19.7350,85.4700,2024-02-12T09:15:00Z,salinity,14.2,psu,,0.5,
St. B,19.8100,85.5200,2024-02-12T10:20:00Z,dissolved_oxygen,5.9,mg/L,,1.0,
St. B,19.8100,85.5200,2024-02-12T10:20:00Z,salinity,13.8,psu,,1.0,
St. A,19.7350,85.4700,2024-03-10T09:00:00Z,dissolved_oxygen,7.2,mg/L,,0.5,
St. A,19.7350,85.4700,2024-03-10T09:00:00Z,salinity,11.9,psu,,0.5,
St. B,19.8100,85.5200,2024-03-10T09:45:00Z,dissolved_oxygen,6.1,mg/L,,1.0,
St. B,19.8100,85.5200,2024-03-10T09:45:00Z,salinity,nan,psu,,1.0,
"""

_WIDE_CSV = """date;Outer Channel;Central Sector;Northern Sector
2024-01-15;12,4;9,8;7,1
2024-02-12;14,2;10,3;6,9
2024-03-10;11,9;8,7;5,4
2024-04-14;13,6;9,1;6,2
"""

_TSV = """station\tsampled_at\tparameter\tvalue\tunit
St. A\t2024-01-15T09:30:00Z\tdissolved_oxygen\t6.8\tmg/L
St. B\t2024-01-15T10:05:00Z\tsalinity\t12.4\tpsu
St. A\t2024-02-12T09:15:00Z\tdissolved_oxygen\t25.0\tmg/L
St. B\t2024-02-12T10:20:00Z\tsalinity\t13.8\tpsu
"""

_RAGGED_CSV = """station,latitude,longitude,sampled_at,parameter,value
St. A,19.7350,85.4700,2024-01-15T09:30:00Z,dissolved_oxygen,6.8
St. B,19.8100,85.5200,2024-01-15T10:05:00Z,salinity,12.4,extra_field
"""

_UNCLOSED_QUOTE_CSV = """station,notes,parameter,value
St. A,"unterminated note,dissolved_oxygen,6.8
"""

_CP1252_CSV = """station,sampled_at,parameter,value,unit
St. A,2024-01-15T09:30:00Z,temperature,21.4,°C
St. B,2024-01-15T10:05:00Z,phosphat,0.03,µg/l
"""

_BINARY_CSV = b"station,value\n\x00\x01binary\x00\n"

_NO_HEADER_CSV = """St. A,19.7350,85.4700,2024-01-15T09:30:00Z,dissolved_oxygen,6.8,mg/L
St. B,19.8100,85.5200,2024-01-15T10:05:00Z,salinity,12.4,psu
"""

_LONG_MULTI_STATION_CSV = """station,latitude,longitude,sampled_at,parameter,value,unit,qualifier,depth_m,notes
St. A,19.7350,85.4700,2024-01-15T09:30:00Z,dissolved_oxygen,6.8,mg/L,,0.5,
St. B,19.8100,85.5200,2024-01-15T09:30:00Z,dissolved_oxygen,5.9,mg/L,,1.0,
St. C,19.7500,85.4900,2024-01-15T09:30:00Z,dissolved_oxygen,6.1,mg/L,,0.5,
St. D,19.7000,85.4500,2024-01-15T09:30:00Z,dissolved_oxygen,7.0,mg/L,,1.0,
St. A,19.7350,85.4700,2024-02-12T09:15:00Z,dissolved_oxygen,7.2,mg/L,,0.5,
St. B,19.8100,85.5200,2024-02-12T09:15:00Z,dissolved_oxygen,6.4,mg/L,,1.0,
St. C,19.7500,85.4900,2024-02-12T09:15:00Z,dissolved_oxygen,6.6,mg/L,,0.5,
St. D,19.7000,85.4500,2024-02-12T09:15:00Z,dissolved_oxygen,7.4,mg/L,,1.0,
St. A,19.7350,85.4700,2024-03-10T09:00:00Z,dissolved_oxygen,6.9,mg/L,,0.5,
St. B,19.8100,85.5200,2024-03-10T09:00:00Z,dissolved_oxygen,6.2,mg/L,,1.0,
St. C,19.7500,85.4900,2024-03-10T09:00:00Z,dissolved_oxygen,6.5,mg/L,,0.5,
St. D,19.7000,85.4500,2024-03-10T09:00:00Z,dissolved_oxygen,7.1,mg/L,,1.0,
"""

_NOT_A_WORKBOOK = b"station,value\n1,2\n"


def _sha256_of(payload: bytes) -> str:
    """Return the digest of a byte payload."""
    return hashlib.sha256(payload).hexdigest()


def _normalize_zip(payload: bytes) -> bytes:
    """Rewrite a ZIP payload with a fixed member timestamp."""
    normalized = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(payload)) as source,
        zipfile.ZipFile(normalized, "w", zipfile.ZIP_DEFLATED) as target,
    ):
        for info in source.infolist():
            replacement = zipfile.ZipInfo(info.filename, date_time=FIXED_ZIP_TIMESTAMP)
            replacement.compress_type = info.compress_type
            replacement.external_attr = info.external_attr
            target.writestr(replacement, source.read(info.filename))
    return normalized.getvalue()


def _build_workbook() -> bytes:
    """Build the observation workbook fixture."""
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = "Observations"
    sheet.append(["station", "sampled_at", "value", "valid_flag", "collected_on", "computed_total"])
    sheet.append(["St. A", "2024-01-15T09:30:00Z", 6.8, True, datetime(2024, 1, 15, 9, 30), None])
    sheet.append(["St. B", "2024-02-12T10:05:00Z", 12, False, date(2024, 2, 12), None])
    sheet.append(["St. C", "2024-03-10T09:45:00Z", None, True, None, None])
    sheet["F2"] = "=SUM(C2:C3)"
    sheet["F3"] = "=SUM(C3:C4)"
    notes = workbook.create_sheet("Notes")
    notes.append(["Generated deterministically for the ingestion reader tests."])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return _normalize_zip(buffer.getvalue())


def _patch_cell_xml(payload: bytes, pattern: re.Pattern[str], replacement: str) -> bytes:
    """Rewrite one cell in the worksheet XML of a saved workbook.

    OpenPyXL never writes cached values or error cells, so the fixtures that
    exercise those policies are produced by inserting the XML a spreadsheet
    application would have written. The function fails loudly when the pattern
    does not match, so a fixture can never silently lose its purpose.
    """
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        sheet_names = [
            name
            for name in archive.namelist()
            if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)
        ]
        if not sheet_names:
            raise RuntimeError("The workbook fixture contains no worksheet part.")
        patched_parts: dict[str, bytes] = {}
        patched = False
        for name in sheet_names:
            text = archive.read(name).decode("utf-8")
            replacement_text, substitutions = pattern.subn(replacement, text)
            if substitutions:
                patched = True
            patched_parts[name] = replacement_text.encode("utf-8")
    if not patched:
        raise RuntimeError("The cell patch did not match any worksheet part.")
    return _normalize_zip(_repack(payload, patched_parts))


def _repack(payload: bytes, replacements: dict[str, bytes]) -> bytes:
    """Rewrite a ZIP payload, replacing the given members and fixing timestamps."""
    normalized = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(payload)) as source,
        zipfile.ZipFile(normalized, "w", zipfile.ZIP_DEFLATED) as target,
    ):
        for info in source.infolist():
            content = replacements.get(info.filename) or source.read(info.filename)
            replacement = zipfile.ZipInfo(info.filename, date_time=FIXED_ZIP_TIMESTAMP)
            replacement.compress_type = info.compress_type
            replacement.external_attr = info.external_attr
            target.writestr(replacement, content)
    return normalized.getvalue()


def _patch_cached_formula(payload: bytes, cell: str, cached_value: str) -> bytes:
    """Write a cached value into one formula cell of a saved workbook."""
    pattern = re.compile(
        r"(<c r=\"" + re.escape(cell) + r"\"[^>]*>)(<f>[^<]*</f>)(?:<v\s*/>)?(</c>)"
    )
    return _patch_cell_xml(payload, pattern, rf"\g<1>\g<2><v>{cached_value}</v>\g<3>")


def _patch_error_cell(payload: bytes, cell: str, error_code: str) -> bytes:
    """Turn one existing cell into a spreadsheet error cell."""
    pattern = re.compile(r"<c r=\"" + re.escape(cell) + r"\"[^>]*>.*?</c>")
    replacement = f'<c r="{cell}" t="e"><v>{error_code}</v></c>'
    return _patch_cell_xml(payload, pattern, replacement)


def _build_observation_parquet() -> bytes:
    """Build the typed Parquet fixture."""
    table = pa.table(
        {
            "station": pa.array(["St. A", "St. B", "St. C"], pa.string()),
            "value": pa.array([6.8, None, float("nan")], pa.float64()),
            "sampled_at": pa.array(
                [
                    datetime(2024, 1, 15, 9, 30, tzinfo=UTC),
                    datetime(2024, 2, 12, 10, 5, tzinfo=UTC),
                    datetime(2024, 3, 10, 9, 45, tzinfo=UTC),
                ],
                pa.timestamp("us", tz="UTC"),
            ),
            "collected_on": pa.array(
                [date(2024, 1, 15), date(2024, 2, 12), date(2024, 3, 10)], pa.date32()
            ),
            "sample_count": pa.array([3, 2, 5], pa.int32()),
            "is_valid": pa.array([True, False, True], pa.bool_()),
            "salinity": pa.array(
                [Decimal("12.40"), Decimal("9.80"), Decimal("7.25")], pa.decimal128(10, 2)
            ),
            "notes": pa.array([None, "missing value", "non-finite"], pa.string()),
        }
    )
    buffer = io.BytesIO()
    pq.write_table(table, buffer)
    return buffer.getvalue()


def _build_nested_parquet() -> bytes:
    """Build a Parquet fixture whose column cannot be mapped to text."""
    table = pa.table(
        {
            "station": pa.array(["St. A", "St. B"], pa.string()),
            "replicates": pa.array([[1.0, 2.0], [3.0]], pa.list_(pa.float64())),
        }
    )
    buffer = io.BytesIO()
    pq.write_table(table, buffer)
    return buffer.getvalue()


def _build_truncated_parquet() -> bytes:
    """Build a Parquet fixture cut short inside its footer."""
    table = pa.table({"station": pa.array(["St. A", "St. B"], pa.string())})
    buffer = io.BytesIO()
    pq.write_table(table, buffer)
    return buffer.getvalue()[:120]


def build_fixtures() -> dict[str, bytes]:
    """Return every fixture payload by name."""
    workbook = _build_workbook()
    cached_workbook = _patch_cached_formula(workbook, cell="F2", cached_value="18.8")
    error_workbook = _patch_error_cell(workbook, cell="C2", error_code="#DIV/0!")
    return {
        "long_observations.csv": _LONG_CSV.encode("utf-8"),
        "wide_station_matrix.csv": _WIDE_CSV.encode("utf-8"),
        "observations.tsv": _TSV.encode("utf-8"),
        "malformed_ragged.csv": _RAGGED_CSV.encode("utf-8"),
        "malformed_unclosed_quote.csv": _UNCLOSED_QUOTE_CSV.encode("utf-8"),
        "cp1252_non_utf8.csv": _CP1252_CSV.encode("cp1252"),
        "binary_disguised.csv": _BINARY_CSV,
        "no_header_table.csv": _NO_HEADER_CSV.encode("utf-8"),
        "long_multi_station.csv": _LONG_MULTI_STATION_CSV.encode("utf-8"),
        "empty.csv": b"",
        "observations.xlsx": workbook,
        "formulas_cached.xlsx": cached_workbook,
        "error_cells.xlsx": error_workbook,
        "not_a_workbook.xlsx": _NOT_A_WORKBOOK,
        "observations.parquet": _build_observation_parquet(),
        "nested_columns.parquet": _build_nested_parquet(),
        "truncated.parquet": _build_truncated_parquet(),
    }


def write_fixtures() -> dict[str, str]:
    """Write every fixture and return the digest map."""
    TESTDATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
    digests: dict[str, str] = {}
    for name, payload in build_fixtures().items():
        path = TESTDATA_DIRECTORY / name
        path.write_bytes(payload)
        digests[name] = _sha256_of(payload)
    DIGESTS_PATH.write_text(json.dumps(digests, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return digests


def verify_fixtures() -> tuple[bool, list[str]]:
    """Compare the committed fixtures with the recorded digests."""
    if not DIGESTS_PATH.exists():
        return False, [f"{DIGESTS_PATH} is missing; run the generator once"]
    recorded = json.loads(DIGESTS_PATH.read_text(encoding="utf-8"))
    findings: list[str] = []
    for name, digest in sorted(recorded.items()):
        path = TESTDATA_DIRECTORY / name
        if not path.exists():
            findings.append(f"{name} is missing")
            continue
        actual = _sha256_of(path.read_bytes())
        if actual != digest:
            findings.append(f"{name} does not match its recorded digest")
    for path in sorted(TESTDATA_DIRECTORY.iterdir()):
        if path.name in {"digests.json", "README.md"}:
            continue
        if path.name not in recorded:
            findings.append(f"{path.name} is not recorded in {DIGESTS_PATH.name}")
    return not findings, findings


def main(argv: list[str] | None = None) -> int:
    """Run the generator."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify that the committed fixtures match the recorded digests",
    )
    arguments = parser.parse_args(argv)

    if arguments.check:
        passed, findings = verify_fixtures()
        for finding in findings:
            print(f"make_testdata: {finding}")
        print(
            "make_testdata: the committed fixtures match the recorded digests"
            if passed
            else "make_testdata: the fixtures are out of date"
        )
        return 0 if passed else 1

    digests = write_fixtures()
    for name, digest in sorted(digests.items()):
        print(f"{digest}  {name}")
    print(f"make_testdata: wrote {len(digests)} fixtures to {TESTDATA_DIRECTORY}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
