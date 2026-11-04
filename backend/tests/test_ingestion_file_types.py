"""Tests for extension, container, and magic-byte validation."""

from __future__ import annotations

import io

import pytest

from trendsmapp.domain.enums import FileFormat
from trendsmapp.errors import ValidationError
from trendsmapp.ingestion.file_types import (
    FileTypeVerdict,
    detect_format_from_magic,
    format_for_extension,
    inspect_file_type,
    looks_like_text,
    normalize_content_type,
    normalized_extension,
)
from trendsmapp.ingestion.security import require_seekable


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


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("table.csv", ".csv"),
        ("TABLE.CSV", ".csv"),
        ("table.TsV", ".tsv"),
        ("book.xlsx", ".xlsx"),
        ("data.parquet", ".parquet"),
        (" spaced.csv ", ".csv"),
    ],
)
def test_normalized_extension_accepts_supported_extensions(filename: str, expected: str) -> None:
    assert normalized_extension(filename) == expected


@pytest.mark.parametrize(
    "filename",
    ["", "   ", "noextension", ".hidden", "trailing."],
)
def test_normalized_extension_rejects_missing_extensions(filename: str) -> None:
    with pytest.raises(ValidationError):
        normalized_extension(filename)


def test_normalized_extension_names_the_legacy_format() -> None:
    with pytest.raises(ValidationError) as error:
        normalized_extension("legacy.xls")
    assert ".xls" in str(error.value)
    assert ".xlsx" in str(error.value)


def test_normalized_extension_rejects_unknown_extensions() -> None:
    with pytest.raises(ValidationError):
        normalized_extension("table.json")


def test_format_for_extension_maps_every_supported_extension() -> None:
    assert format_for_extension(".csv") is FileFormat.CSV
    assert format_for_extension(".tsv") is FileFormat.TSV
    assert format_for_extension(".xlsx") is FileFormat.XLSX
    assert format_for_extension(".parquet") is FileFormat.PARQUET


def test_format_for_extension_rejects_unsupported_extensions() -> None:
    with pytest.raises(ValidationError):
        format_for_extension(".json")


def test_normalize_content_type_strips_parameters() -> None:
    assert normalize_content_type(None) is None
    assert normalize_content_type("") is None
    assert normalize_content_type("Text/CSV; charset=utf-8") == "text/csv"


def test_detect_format_from_magic_recognizes_containers() -> None:
    assert detect_format_from_magic(b"PK\x03\x04rest") is FileFormat.XLSX
    assert detect_format_from_magic(b"PK\x05\x06rest") is FileFormat.XLSX
    assert detect_format_from_magic(b"PK\x07\x08rest") is FileFormat.XLSX
    assert detect_format_from_magic(b"PAR1rest") is FileFormat.PARQUET
    assert detect_format_from_magic(b"station,value\n1,2\n") is None


def test_looks_like_text_accepts_text_and_rejects_binary() -> None:
    assert looks_like_text(b"station,value\n1,2\n")
    assert looks_like_text(b"caf\xc3\xa9,20.5\n")
    assert not looks_like_text(b"station,value\n\x00\x01binary\x00\n")
    assert not looks_like_text(b"")
    control_bytes = bytes([1, 2, 3, 4, 5, 6, 7, 8] * 32)
    assert not looks_like_text(control_bytes)


def test_inspect_file_type_accepts_a_text_table() -> None:
    verdict = inspect_file_type(
        filename="table.csv", content_type="text/csv", head=b"station,value\n1,2\n"
    )
    assert isinstance(verdict, FileTypeVerdict)
    assert verdict.format is FileFormat.CSV
    assert verdict.magic_format is None
    assert verdict.content_type_accepted is True
    assert verdict.warnings == ()


def test_inspect_file_type_accepts_a_workbook_container() -> None:
    head = b"PK\x03\x04" + b"\x00" * 60
    verdict = inspect_file_type(filename="book.xlsx", content_type=None, head=head)
    assert verdict.format is FileFormat.XLSX
    assert verdict.magic_format is FileFormat.XLSX
    assert verdict.content_type_accepted is None


def test_inspect_file_type_warns_about_an_unexpected_mime_type() -> None:
    verdict = inspect_file_type(
        filename="table.csv", content_type="application/x-strange", head=b"a,b\n1,2\n"
    )
    assert verdict.content_type_accepted is False
    assert len(verdict.warnings) == 1
    assert "application/x-strange" in verdict.warnings[0]


def test_inspect_file_type_rejects_a_zip_named_as_csv() -> None:
    with pytest.raises(ValidationError) as error:
        inspect_file_type(filename="table.csv", content_type=None, head=b"PK\x03\x04rest")
    assert "container" in str(error.value)


def test_inspect_file_type_rejects_text_named_as_workbook() -> None:
    with pytest.raises(ValidationError) as error:
        inspect_file_type(filename="book.xlsx", content_type=None, head=b"station,value\n")
    assert "ZIP" in str(error.value)


def test_inspect_file_type_rejects_text_named_as_parquet() -> None:
    with pytest.raises(ValidationError) as error:
        inspect_file_type(filename="data.parquet", content_type=None, head=b"station,value\n")
    assert "Parquet" in str(error.value)


def test_inspect_file_type_rejects_binary_named_as_csv() -> None:
    payload = b"station,value\n\x00\x01binary\x00\n"
    with pytest.raises(ValidationError) as error:
        inspect_file_type(filename="binary.csv", content_type=None, head=payload)
    assert "text" in str(error.value)


def test_inspect_file_type_accepts_a_parquet_signature() -> None:
    head = b"PAR1" + b"\x00" * 60
    verdict = inspect_file_type(filename="data.parquet", content_type=None, head=head)
    assert verdict.format is FileFormat.PARQUET
    assert verdict.magic_format is FileFormat.PARQUET


def test_require_seekable_rejects_non_seekable_streams() -> None:
    require_seekable(io.BytesIO(b"data"), context="a test")
    with pytest.raises(ValidationError):
        require_seekable(NonSeekableStream(b"data"), context="a test")
