"""Tests for encoding, delimiter, header, decimal, and layout detection."""

from __future__ import annotations

from pathlib import Path

import pytest

from trendsmapp.domain.enums import FileFormat, LayoutKind
from trendsmapp.errors import ParsingError, ValidationError
from trendsmapp.ingestion.sniffing import (
    DecimalStyle,
    detect_decimal_style,
    detect_delimiter,
    detect_encoding,
    detect_header,
    detect_layout,
    is_date_like_token,
    is_numeric_token,
    sample_columns,
    sniff,
    sniff_delimited_bytes,
)

LONG_HEADER = ("station", "latitude", "longitude", "sampled_at", "parameter", "value", "unit")


def test_detect_encoding_returns_utf8_without_warning() -> None:
    detection = detect_encoding(b"station,value\n1,2\n")
    assert detection.encoding == "utf-8"
    assert detection.confidence == pytest.approx(0.95)
    assert detection.warnings == ()


def test_detect_encoding_honors_a_byte_order_mark() -> None:
    utf8_bom = detect_encoding(b"\xef\xbb\xbfstation,value\n")
    assert utf8_bom.encoding == "utf-8-sig"
    assert utf8_bom.confidence == pytest.approx(1.0)

    utf16_bom = detect_encoding(b"\xff\xfes\x00t\x00a\x00")
    assert utf16_bom.encoding == "utf-16"
    assert utf16_bom.confidence == pytest.approx(1.0)


def test_detect_encoding_falls_back_to_windows_1252() -> None:
    payload = "station,unit\nA,°C\n".encode("cp1252")
    detection = detect_encoding(payload)
    assert detection.encoding == "cp1252"
    assert detection.confidence == pytest.approx(0.5)
    assert detection.warnings
    assert "Windows-1252" in detection.warnings[0]


def test_detect_encoding_rejects_empty_and_binary_payloads() -> None:
    with pytest.raises(ParsingError):
        detect_encoding(b"")
    with pytest.raises(ParsingError):
        detect_encoding(b"\x81\x8d\x8f\x90\x9d")


def test_detect_delimiter_finds_each_common_delimiter() -> None:
    comma = detect_delimiter("a,b,c\n1,2,3\n4,5,6\n")
    assert comma.delimiter == ","
    assert comma.confidence == pytest.approx(1.0)
    assert comma.field_counts == (3, 3, 3)

    semicolon = detect_delimiter("a;b;c\n1;2;3\n4;5;6\n")
    assert semicolon.delimiter == ";"

    tabbed = detect_delimiter("a\tb\tc\n1\t2\t3\n4\t5\t6\n")
    assert tabbed.delimiter == "\t"

    piped = detect_delimiter("a|b|c\n1|2|3\n4|5|6\n")
    assert piped.delimiter == "|"


def test_detect_delimiter_ignores_delimiters_inside_quotes() -> None:
    detection = detect_delimiter('a,b,c\n"x,y",2,3\n"p,q",5,6\n')
    assert detection.delimiter == ","
    assert detection.field_counts == (3, 3, 3)


def test_count_outside_quotes_handles_escaped_quotes() -> None:
    from trendsmapp.ingestion.sniffing import count_outside_quotes

    assert count_outside_quotes('"say ""hi"", ok",2', ",") == 1
    assert count_outside_quotes('"plain",text', ",") == 1


def test_detect_delimiter_reports_single_column_tables() -> None:
    detection = detect_delimiter("single\nvalues\nonly\n")
    assert detection.confidence == 0.0
    assert detection.field_counts == (1, 1, 1)


def test_detect_header_accepts_named_unique_columns() -> None:
    rows = [("station", "value", "unit"), ("A", "1.5", "mg/L"), ("B", "2.0", "mg/L")]
    detection = detect_header(rows)
    assert detection.has_header is True
    assert detection.fields == ("station", "value", "unit")
    assert detection.confidence == pytest.approx(1.0)


def test_detect_header_rejects_data_first_rows() -> None:
    rows = [("19.7350", "6.8", "mg/L"), ("19.8100", "12.4", "psu")]
    detection = detect_header(rows)
    assert detection.has_header is False

    dated = [("2024-01-15", "6.8"), ("2024-02-12", "12.4")]
    assert detect_header(dated).has_header is False


def test_detect_header_renames_duplicate_names_instead_of_rejecting_the_header() -> None:
    rows = [("station", "value", "VALUE"), ("A", "1.5", "2.5"), ("B", "3.5", "4.5")]
    detection = detect_header(rows)
    assert detection.has_header is True
    assert detection.confidence < 1.0


def test_detect_decimal_style_detects_point_and_comma() -> None:
    point_rows = [("1.5", "2.5"), ("3.25", "4.0")]
    style, warnings = detect_decimal_style(point_rows)
    assert style is DecimalStyle.POINT
    assert warnings == ()

    comma_rows = [("1,5", "2,5"), ("3,25", "4,0"), ("5,75", "6,125"), ("7,5", "8,5")]
    style, warnings = detect_decimal_style(comma_rows)
    assert style is DecimalStyle.COMMA
    assert warnings == ()


def test_detect_decimal_style_warns_about_mixed_conventions() -> None:
    style, warnings = detect_decimal_style([("1,5", "2.5"), ("3,25", "4.0"), ("5,75", "6.5")])
    assert style is DecimalStyle.POINT
    assert warnings
    assert "decimal separators" in warnings[0]


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("2024-01-15", True),
        ("2024-01-15T09:30:00Z", True),
        ("2024-01-15 09:30:00", True),
        ("2024-01", True),
        ("2024/01/15", True),
        ("15/01/2024", True),
        ("15-01-2024", True),
        ("15.01.2024", True),
        ("Jan 2024", True),
        ("15 Jan 2024", True),
        ("2024", False),
        ("nan", False),
        ("12.4", False),
        ("", False),
        ("salinity", False),
    ],
)
def test_is_date_like_token_classifies_temporal_evidence(token: str, expected: bool) -> None:
    assert is_date_like_token(token) is expected


@pytest.mark.parametrize(
    ("token", "style", "expected"),
    [
        ("6.8", DecimalStyle.POINT, True),
        ("25.0", DecimalStyle.POINT, True),
        ("-3.5e2", DecimalStyle.POINT, True),
        ("1,234.5", DecimalStyle.POINT, True),
        ("1,5", DecimalStyle.COMMA, True),
        ("1.234,5", DecimalStyle.COMMA, True),
        ("<0.01", DecimalStyle.POINT, True),
        (">25", DecimalStyle.POINT, True),
        ("≤0.05", DecimalStyle.POINT, True),
        ("nan", DecimalStyle.POINT, False),
        ("inf", DecimalStyle.POINT, False),
        ("12 mg", DecimalStyle.POINT, False),
        ("mg/L", DecimalStyle.POINT, False),
        ("", DecimalStyle.POINT, False),
        ("station", DecimalStyle.POINT, False),
    ],
)
def test_is_numeric_token_classifies_value_evidence(
    token: str, style: DecimalStyle, expected: bool
) -> None:
    assert is_numeric_token(token, style) is expected


def test_sample_columns_reports_numeric_and_date_fractions() -> None:
    rows = [
        ("A", "19.7350", "2024-01-15"),
        ("B", "19.8100", "2024-02-12"),
        ("C", "19.9000", ""),
        ("D", "20.1000", "2024-04-14"),
    ]
    fields = ("station", "latitude", "sampled_at")
    columns = sample_columns(rows, fields, style=DecimalStyle.POINT)
    assert [column.name for column in columns] == list(fields)

    station = columns[0]
    assert station.is_numeric is False
    assert station.distinct_count == 4
    assert station.samples == ("A", "B", "C", "D")

    latitude = columns[1]
    assert latitude.is_numeric is True
    assert latitude.numeric_fraction == pytest.approx(1.0)

    sampled_at = columns[2]
    assert sampled_at.date_fraction == pytest.approx(1.0)
    assert sampled_at.is_date_like is True


def test_sample_columns_pads_missing_cells() -> None:
    rows = [("A", "1.0"), ("B",)]
    columns = sample_columns(rows, ("station", "value", "extra"), style=DecimalStyle.POINT)
    assert columns[2].non_empty_count == 0
    assert columns[2].numeric_fraction == 0.0


def test_detect_layout_classifies_the_long_fixture(testdata_path: Path) -> None:
    result = sniff_delimited_bytes(
        testdata_path("long_observations.csv").read_bytes(), file_format=FileFormat.CSV
    )
    assert result.layout.layout is LayoutKind.LONG
    assert result.layout.confidence == pytest.approx(0.9)
    assert result.layout.warnings == ()
    assert any("date-like" in item for item in result.layout.evidence)
    assert any("parameter column" in item for item in result.layout.evidence)


def test_detect_layout_classifies_the_wide_fixture(testdata_path: Path) -> None:
    result = sniff_delimited_bytes(
        testdata_path("wide_station_matrix.csv").read_bytes(), file_format=FileFormat.CSV
    )
    assert result.layout.layout is LayoutKind.WIDE
    assert result.layout.confidence == pytest.approx(0.9)
    assert result.layout.warnings
    assert "mapping step must confirm" in result.layout.warnings[0]


def test_detect_layout_reports_unknown_without_evidence() -> None:
    fields = ("notes", "comments")
    columns = sample_columns(
        [("some text", "more text"), ("another", "row")],
        fields,
        style=DecimalStyle.POINT,
    )
    layout = detect_layout(fields=fields, columns=columns, has_header=True)
    assert layout.layout is LayoutKind.UNKNOWN
    assert layout.confidence == 0.0
    assert layout.warnings


def test_detect_layout_treats_a_dateless_numeric_matrix_as_wide() -> None:
    fields = ("site_a", "site_b", "site_c")
    rows = [("1.5", "2.5", "3.5"), ("4.5", "5.5", "6.5"), ("7.5", "8.5", "9.5")]
    columns = sample_columns(rows, fields, style=DecimalStyle.POINT)
    layout = detect_layout(fields=fields, columns=columns, has_header=True)
    assert layout.layout is LayoutKind.UNKNOWN
    assert layout.warnings


def test_detect_layout_names_coordinate_columns_as_excluded_evidence() -> None:
    fields = ("sampled_at", "latitude", "value")
    rows = [
        ("2024-01-15", "19.7350", "6.8"),
        ("2024-02-12", "19.8100", "12.4"),
    ]
    columns = sample_columns(rows, fields, style=DecimalStyle.POINT)
    layout = detect_layout(fields=fields, columns=columns, has_header=True)
    assert any("coordinate" in item for item in layout.evidence)


def test_sniff_describes_the_long_fixture(testdata_path: Path) -> None:
    result = sniff_delimited_bytes(
        testdata_path("long_observations.csv").read_bytes(), file_format=FileFormat.CSV
    )
    assert result.file_format is FileFormat.CSV
    assert result.encoding == "utf-8"
    assert result.delimiter == ","
    assert result.has_header is True
    assert result.header_row_index == 0
    assert result.fields == (*LONG_HEADER, "qualifier", "depth_m", "notes")
    assert result.decimal_style is DecimalStyle.POINT
    assert len(result.sample_rows) == 13
    assert result.sample_rows[0] == (
        "station",
        "latitude",
        "longitude",
        "sampled_at",
        "parameter",
        "value",
        "unit",
        "qualifier",
        "depth_m",
        "notes",
    )
    value_column = result.columns[5]
    assert value_column.name == "value"
    assert value_column.numeric_fraction == pytest.approx(0.909, abs=1e-3)
    assert "<0.01" in value_column.samples


def test_sniff_names_positional_columns_without_a_header(testdata_path: Path) -> None:
    result = sniff_delimited_bytes(
        testdata_path("no_header_table.csv").read_bytes(), file_format=FileFormat.CSV
    )
    assert result.has_header is False
    assert result.header_row_index is None
    assert result.fields == tuple(f"column_{index}" for index in range(1, 8))
    assert any("by position" in warning for warning in result.warnings)


def test_sniff_uniquifies_duplicate_header_names() -> None:
    result = sniff(
        [("station", "value", "value"), ("A", "1.0", "2.0"), ("B", "3.0", "4.0")],
        file_format=FileFormat.CSV,
    )
    assert result.has_header is True
    assert result.fields == ("station", "value", "value_2")
    assert any("appears more than once" in warning for warning in result.warnings)


def test_sniff_rejects_binary_content(testdata_path: Path) -> None:
    with pytest.raises(ParsingError) as error:
        sniff_delimited_bytes(
            testdata_path("binary_disguised.csv").read_bytes(), file_format=FileFormat.CSV
        )
    assert "binary" in str(error.value)


def test_sniff_rejects_an_empty_file(testdata_path: Path) -> None:
    with pytest.raises(ParsingError):
        sniff_delimited_bytes(testdata_path("empty.csv").read_bytes(), file_format=FileFormat.CSV)


def test_sniff_rejects_non_delimited_formats() -> None:
    with pytest.raises(ValidationError):
        sniff_delimited_bytes(b"PK\x03\x04", file_format=FileFormat.XLSX)


def test_sniff_reports_a_truncated_sample() -> None:
    result = sniff(
        [("station", "value"), ("A", "1.0")],
        file_format=FileFormat.CSV,
        sample_truncated=True,
    )
    assert any("incomplete" in warning for warning in result.warnings)


def test_sniff_tsv_detects_tab_delimiters(testdata_path: Path) -> None:
    result = sniff_delimited_bytes(
        testdata_path("observations.tsv").read_bytes(), file_format=FileFormat.TSV
    )
    assert result.file_format is FileFormat.TSV
    assert result.delimiter == "\t"
    assert result.has_header is True
    assert result.layout.layout is LayoutKind.LONG
