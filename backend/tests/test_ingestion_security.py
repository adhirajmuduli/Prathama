"""Tests for upload defenses: size, archive, workbook, and stream limits."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from trendsmapp.constants import (
    MAX_INGESTED_COLUMNS,
    MAX_INGESTED_ROWS,
    MAX_WORKBOOK_CELLS,
    MAX_WORKBOOK_SHEETS,
)
from trendsmapp.errors import ResourceLimitError, ValidationError
from trendsmapp.ingestion.security import (
    ZipInspection,
    enforce_cell_ceiling,
    enforce_column_ceiling,
    enforce_row_ceiling,
    enforce_upload_size,
    enforce_workbook_sheet_ceiling,
    enforce_zip_limits,
    inspect_zip_container,
    require_seekable,
    unsafe_member_name,
)


class NonSeekableStream:
    """A minimal non-seekable binary stream."""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self._position = 0

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            data = self._payload[self._position :]
            self._position = len(self._payload)
            return data
        data = self._payload[self._position : self._position + size]
        self._position += len(data)
        return data

    def readable(self) -> bool:
        return True


def _zip_bytes(*members: tuple[str, bytes]) -> bytes:
    """Build an in-memory ZIP archive with the given members."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in members:
            archive.writestr(name, payload)
    return buffer.getvalue()


def _base_inspection() -> ZipInspection:
    """Return an inspection record within every limit."""
    return ZipInspection(
        member_count=10,
        total_uncompressed_bytes=17_000,
        largest_member_bytes=4_000,
        max_member_ratio=4.0,
        macro_members=(),
        unsafe_member_names=(),
        nested_archive_members=(),
        ratio_violation_members=(),
    )


def test_enforce_upload_size_rejects_negative_and_oversized_uploads() -> None:
    enforce_upload_size(1024, maximum_bytes=2048)
    with pytest.raises(ValidationError):
        enforce_upload_size(-1, maximum_bytes=2048)
    with pytest.raises(ResourceLimitError) as error:
        enforce_upload_size(2049, maximum_bytes=2048)
    assert error.value.details["size_bytes"] == 2049
    assert error.value.details["maximum_bytes"] == 2048


def test_enforce_row_ceiling_rejects_tables_above_the_ceiling() -> None:
    enforce_row_ceiling(MAX_INGESTED_ROWS)
    with pytest.raises(ResourceLimitError):
        enforce_row_ceiling(MAX_INGESTED_ROWS + 1)


def test_enforce_column_ceiling_rejects_tables_above_the_ceiling() -> None:
    enforce_column_ceiling(MAX_INGESTED_COLUMNS)
    with pytest.raises(ResourceLimitError):
        enforce_column_ceiling(MAX_INGESTED_COLUMNS + 1)


def test_enforce_workbook_sheet_ceiling_rejects_extra_sheets() -> None:
    enforce_workbook_sheet_ceiling(MAX_WORKBOOK_SHEETS)
    with pytest.raises(ResourceLimitError):
        enforce_workbook_sheet_ceiling(MAX_WORKBOOK_SHEETS + 1)


def test_enforce_cell_ceiling_rejects_extra_cells() -> None:
    enforce_cell_ceiling(MAX_WORKBOOK_CELLS)
    with pytest.raises(ResourceLimitError):
        enforce_cell_ceiling(MAX_WORKBOOK_CELLS + 1)


def test_inspect_zip_container_describes_a_workbook(testdata_path: Path) -> None:
    payload = testdata_path("observations.xlsx").read_bytes()
    stream = io.BytesIO(payload)
    inspection = inspect_zip_container(stream)
    assert inspection.member_count > 0
    assert inspection.total_uncompressed_bytes > 0
    assert inspection.is_safe
    assert inspection.macro_members == ()
    assert stream.tell() == 0


def test_inspect_zip_container_rejects_non_zip_payloads() -> None:
    with pytest.raises(ValidationError) as error:
        inspect_zip_container(io.BytesIO(b"station,value\n1,2\n"))
    assert "ZIP" in str(error.value)


def test_inspect_zip_container_requires_a_seekable_stream() -> None:
    with pytest.raises(ValidationError):
        inspect_zip_container(NonSeekableStream(b"PK\x03\x04"))


def test_enforce_zip_limits_rejects_macro_workbooks() -> None:
    payload = _zip_bytes(("xl/vbaProject.bin", b"macro bytes"))
    inspection = inspect_zip_container(io.BytesIO(payload))
    with pytest.raises(ValidationError) as error:
        enforce_zip_limits(inspection, label="workbook")
    assert any("vbaProject.bin" in member for member in error.value.details["members"])


def test_enforce_zip_limits_rejects_macro_sheets() -> None:
    payload = _zip_bytes(("xl/macrosheets/sheet1.xml", b"<xml/>"))
    inspection = inspect_zip_container(io.BytesIO(payload))
    with pytest.raises(ValidationError):
        enforce_zip_limits(inspection, label="workbook")


def test_enforce_zip_limits_rejects_traversal_member_names() -> None:
    payload = _zip_bytes(("../evil.xml", b"<xml/>"))
    inspection = inspect_zip_container(io.BytesIO(payload))
    with pytest.raises(ValidationError) as error:
        enforce_zip_limits(inspection, label="workbook")
    assert "../evil.xml" in error.value.details["members"]


def test_enforce_zip_limits_rejects_absolute_member_names() -> None:
    payload = _zip_bytes(("/abs/evil.xml", b"<xml/>"))
    inspection = inspect_zip_container(io.BytesIO(payload))
    with pytest.raises(ValidationError):
        enforce_zip_limits(inspection, label="workbook")


def _zip_with_raw_member_name(member_name: bytes) -> bytes:
    """Build an archive whose stored member name contains a raw backslash.

    Python's ``zipfile`` normalizes backslashes when writing, but an archive
    produced by another tool can carry them. The name is patched in place, at
    equal length, in both the local header and the central directory, so the
    reader sees exactly what a hostile writer could produce. Note that on
    Windows the reader normalizes the name again before it is classified, so
    the classifier itself is covered by a direct test below.
    """
    payload = _zip_bytes(("xl/evil.xml", b"<xml/>"))
    original = b"xl/evil.xml"
    replaced = member_name
    if len(original) != len(replaced):
        raise ValueError("The replacement name must have the same length.")
    return payload.replace(original, replaced, 2)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("xl/workbook.xml", False),
        ("../evil.xml", True),
        ("./normal.xml", True),
        ("/abs/evil.xml", True),
        ("\\abs\\evil.xml", True),
        ("xl\\evil.xml", True),
        ("C:/evil.xml", True),
        ("", True),
    ],
)
def test_unsafe_member_name_classifies_hostile_names(name: str, expected: bool) -> None:
    assert unsafe_member_name(name) is expected


def test_inspect_zip_container_flags_traversal_member_names() -> None:
    """Traversal names survive zipfile on every platform and must be flagged."""
    payload = _zip_bytes(("../evil.xml", b"<xml/>"))
    inspection = inspect_zip_container(io.BytesIO(payload))
    assert inspection.unsafe_member_names == ("../evil.xml",)
    with pytest.raises(ValidationError):
        enforce_zip_limits(inspection, label="workbook")


def test_enforce_zip_limits_rejects_nested_archives() -> None:
    payload = _zip_bytes(("xl/embedded.zip", b"PK\x03\x04"))
    inspection = inspect_zip_container(io.BytesIO(payload))
    with pytest.raises(ValidationError) as error:
        enforce_zip_limits(inspection, label="workbook")
    assert "xl/embedded.zip" in error.value.details["members"]


def test_enforce_zip_limits_rejects_executable_members() -> None:
    payload = _zip_bytes(("xl/embedded.exe", b"MZ"))
    inspection = inspect_zip_container(io.BytesIO(payload))
    with pytest.raises(ValidationError):
        enforce_zip_limits(inspection, label="workbook")


def test_enforce_zip_limits_rejects_decompression_bombs() -> None:
    compressed_member = b"a" * (2 * 1024 * 1024)
    payload = _zip_bytes(("xl/large.xml", compressed_member))
    inspection = inspect_zip_container(io.BytesIO(payload))
    assert inspection.ratio_violation_members == ("xl/large.xml",)
    with pytest.raises(ResourceLimitError):
        enforce_zip_limits(inspection, label="workbook")


def test_enforce_zip_limits_allows_well_compressed_small_members() -> None:
    """Members below the ratio-check floor are exempt, whatever their ratio."""
    payload = _zip_bytes(("xl/styles.xml", b"<" * (512 * 1024)))
    inspection = inspect_zip_container(io.BytesIO(payload))
    assert inspection.ratio_violation_members == ()
    enforce_zip_limits(inspection, label="workbook")


def test_enforce_zip_limits_rejects_too_many_members() -> None:
    inspection = ZipInspection(
        member_count=5_001,
        total_uncompressed_bytes=1_000,
        largest_member_bytes=10,
        max_member_ratio=1.0,
        macro_members=(),
        unsafe_member_names=(),
        nested_archive_members=(),
        ratio_violation_members=(),
    )
    with pytest.raises(ResourceLimitError) as error:
        enforce_zip_limits(inspection, label="workbook")
    assert error.value.details["members"] == 5_001


def test_enforce_zip_limits_rejects_expansion_above_the_ceiling() -> None:
    inspection = ZipInspection(
        member_count=2,
        total_uncompressed_bytes=513 * 1024 * 1024,
        largest_member_bytes=512 * 1024 * 1024,
        max_member_ratio=2.0,
        macro_members=(),
        unsafe_member_names=(),
        nested_archive_members=(),
        ratio_violation_members=(),
    )
    with pytest.raises(ResourceLimitError) as error:
        enforce_zip_limits(inspection, label="workbook")
    assert error.value.details["uncompressed_bytes"] == 513 * 1024 * 1024


def test_enforce_zip_limits_accepts_a_safe_container() -> None:
    enforce_zip_limits(_base_inspection(), label="workbook")


def test_require_seekable_accepts_only_seekable_streams() -> None:
    require_seekable(io.BytesIO(b"ok"), context="test")
    with pytest.raises(ValidationError):
        require_seekable(NonSeekableStream(b"blocked"), context="test")
