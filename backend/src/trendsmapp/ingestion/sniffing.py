"""Encoding, delimiter, header, decimal, and layout detection with evidence.

The sniffer never parses scientific values. It reports what a table *looks*
like, together with the evidence and a confidence, so that the mapping step can
propose a layout and the analyst can overrule it. A guess is therefore always
visible as a guess: every decision carries the evidence that produced it, and a
weak decision carries a warning.

The date-like classifier in this module exists only to describe a column as
evidence for layout detection. The authoritative timestamp parse, with the
declared date order and timezone policy, lives in
:mod:`trendsmapp.normalization.timestamps`.
"""

from __future__ import annotations

import csv
import io
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from trendsmapp.constants import SNIFF_SAMPLE_ROWS
from trendsmapp.domain.enums import FileFormat, LayoutKind
from trendsmapp.errors import ParsingError, ValidationError

__all__ = [
    "BOM_KINDS",
    "ColumnSample",
    "DecimalStyle",
    "DelimiterDetection",
    "EncodingDetection",
    "HeaderDetection",
    "LayoutDetection",
    "SniffResult",
    "detect_decimal_style",
    "detect_delimiter",
    "detect_encoding",
    "detect_header",
    "detect_layout",
    "normalize_header_name",
    "sniff",
    "sniff_delimited_bytes",
]

#: Delimiters considered when a delimited file is sniffed.
DELIMITER_CANDIDATES: Final[tuple[str, ...]] = (",", ";", "\t", "|")

#: The characters that mark a quoted field in a delimited file.
_QUOTE_CHAR: Final[str] = '"'

#: How many non-empty values per column are kept as examples.
_COLUMN_SAMPLE_VALUES: Final[int] = 12

#: The number of decimal tokens a comma-decimal file must show before the
#: convention is switched away from the default.
_MIN_COMMA_DECIMAL_EVIDENCE: Final[int] = 5

#: A leading qualifier is stripped before a token is tested for numericity.
_QUALIFIER_PREFIXES: Final[tuple[str, ...]] = ("<", ">", "≤", "≥", "~")

_ISO_DATE = re.compile(
    r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?)?$"
)
_ISO_MONTH = re.compile(r"^\d{4}-\d{2}$")
_SLASHED_DATE = re.compile(r"^(\d{4}/\d{1,2}/\d{1,2}|\d{1,2}/\d{1,2}/\d{4})([ T].*)?$")
_DAY_FIRST_DATE = re.compile(r"^\d{1,2}[-.]\d{1,2}[-.]\d{4}([ T].*)?$")
_MONTH_NAME_DATE = re.compile(
    r"^(\d{1,2}[- ](jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[- ]\d{2,4}"
    r"|(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[- ]\d{1,2},?[- ]\d{2,4}"
    r"|(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[- ]\d{4})$",
    re.IGNORECASE,
)
_POINT_DECIMAL = re.compile(r"^[+-]?\d{1,3}(,\d{3})*\.\d+$")
_COMMA_DECIMAL = re.compile(r"^[+-]?\d{1,3}(\.\d{3})*,\d+$")
_PLAIN_NUMBER = re.compile(r"^[+-]?(\d{1,3}(,\d{3})+|\d+)(\.\d+)?([eE][+-]?\d+)?$")

#: Header-name hints. They are deliberately broad and documented as hints: the
#: analyst confirms the mapping, and the parameter registry resolves aliases in
#: the mapping step.
TIMESTAMP_NAME_HINTS: Final[tuple[str, ...]] = (
    "date",
    "time",
    "timestamp",
    "datetime",
    "sampled_at",
    "sample_date",
    "sampling_date",
    "observation_date",
    "month",
    "year_month",
)
PARAMETER_NAME_HINTS: Final[tuple[str, ...]] = (
    "parameter",
    "param",
    "analyte",
    "variable",
    "constituent",
    "measurement",
    "metric",
    "indicator",
)
VALUE_NAME_HINTS: Final[tuple[str, ...]] = (
    "value",
    "result",
    "reading",
    "concentration",
    "observed",
    "mean",
    "average",
)
COORDINATE_NAME_HINTS: Final[tuple[str, ...]] = (
    "lat",
    "latitude",
    "lon",
    "long",
    "longitude",
    "easting",
    "northing",
    "utm",
    "coord",
)
STATION_NAME_HINTS: Final[tuple[str, ...]] = (
    "station",
    "site",
    "location",
    "stn",
    "monitoring_point",
    "sampling_point",
)
UNIT_NAME_HINTS: Final[tuple[str, ...]] = ("unit", "units", "uom", "unit_of_measure")

BOM_KINDS: Final[tuple[tuple[bytes, str], ...]] = (
    (b"\xef\xbb\xbf", "utf-8-sig"),
    (b"\xff\xfe", "utf-16"),
    (b"\xfe\xff", "utf-16"),
)

#: Encodings a delimited file may be decoded with, in order of preference.
_TEXT_ENCODINGS: Final[tuple[str, ...]] = ("utf-8", "cp1252")


class DecimalStyle(StrEnum):
    """The decimal convention a delimited file appears to use."""

    POINT = "point"
    COMMA = "comma"


@dataclass(frozen=True, slots=True)
class EncodingDetection:
    """The encoding a text sample was decoded with."""

    encoding: str
    confidence: float
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DelimiterDetection:
    """The delimiter a delimited file appears to use."""

    delimiter: str
    field_counts: tuple[int, ...]
    confidence: float


@dataclass(frozen=True, slots=True)
class HeaderDetection:
    """Whether the first row is a header, and the field names it carries."""

    has_header: bool
    fields: tuple[str, ...]
    confidence: float


@dataclass(frozen=True, slots=True)
class ColumnSample:
    """What a bounded sample of one column looks like."""

    name: str
    samples: tuple[str, ...]
    non_empty_count: int
    numeric_fraction: float
    date_fraction: float
    distinct_count: int

    @property
    def is_numeric(self) -> bool:
        """Return whether the column is numeric across the sample."""
        return self.numeric_fraction >= 0.8

    @property
    def is_date_like(self) -> bool:
        """Return whether the column is date-like across the sample."""
        return self.date_fraction >= 0.6


@dataclass(frozen=True, slots=True)
class LayoutDetection:
    """The table layout the evidence supports."""

    layout: LayoutKind
    confidence: float
    evidence: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SniffResult:
    """Everything the sniffer established about one table.

    ``sample_rows`` holds every sampled row, including the header row when one
    was detected, so a report can show the raw evidence alongside the decision.
    """

    file_format: FileFormat
    encoding: str | None
    delimiter: str | None
    has_header: bool
    fields: tuple[str, ...]
    header_row_index: int | None
    decimal_style: DecimalStyle
    columns: tuple[ColumnSample, ...]
    layout: LayoutDetection
    sample_rows: tuple[tuple[str, ...], ...]
    warnings: tuple[str, ...]


def detect_encoding(head: bytes) -> EncodingDetection:
    """Return the encoding a byte sample should be decoded with."""
    if not head:
        raise ParsingError("The file is empty, so its encoding cannot be determined.")
    for marker, encoding in BOM_KINDS:
        if head.startswith(marker):
            return EncodingDetection(encoding=encoding, confidence=1.0, warnings=())
    fallback_warnings: list[str] = []
    for encoding in _TEXT_ENCODINGS:
        try:
            head.decode(encoding, errors="strict")
        except UnicodeDecodeError:
            continue
        if encoding == "utf-8":
            return EncodingDetection(encoding=encoding, confidence=0.95, warnings=())
        fallback_warnings.append("The file is not valid UTF-8; it was decoded as Windows-1252.")
        return EncodingDetection(
            encoding=encoding, confidence=0.5, warnings=tuple(fallback_warnings)
        )
    raise ParsingError("The file could not be decoded as text with any supported encoding.")


def count_outside_quotes(line: str, character: str) -> int:
    """Count ``character`` in ``line`` while ignoring quoted regions."""
    count = 0
    in_quotes = False
    index = 0
    while index < len(line):
        current = line[index]
        if current == _QUOTE_CHAR:
            if in_quotes and index + 1 < len(line) and line[index + 1] == _QUOTE_CHAR:
                index += 2
                continue
            in_quotes = not in_quotes
        elif current == character and not in_quotes:
            count += 1
        index += 1
    return count


def detect_delimiter(
    text: str, *, candidates: tuple[str, ...] = DELIMITER_CANDIDATES
) -> DelimiterDetection:
    """Return the delimiter whose field counts are the most consistent.

    A table without a multi-field record has no delimiter; the detection then
    reports the default comma with zero confidence and the observed field
    counts, so the parse report can still describe what was seen.
    """
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return DelimiterDetection(delimiter=",", field_counts=(), confidence=0.0)
    fallback_counts: tuple[int, ...] = ()
    best = DelimiterDetection(delimiter=",", field_counts=(), confidence=0.0)
    for candidate in candidates:
        counts = tuple(count_outside_quotes(line, candidate) + 1 for line in lines)
        if not fallback_counts:
            fallback_counts = counts
        modal_count, modal_frequency = Counter(counts).most_common(1)[0]
        if modal_count < 2:
            continue
        confidence = modal_frequency / len(counts)
        if confidence > best.confidence:
            best = DelimiterDetection(
                delimiter=candidate, field_counts=counts, confidence=round(confidence, 3)
            )
    if best.confidence == 0.0 and fallback_counts:
        return DelimiterDetection(delimiter=",", field_counts=fallback_counts, confidence=0.0)
    return best


def detect_header(rows: Sequence[Sequence[str]]) -> HeaderDetection:
    """Return whether the first row looks like a header.

    A duplicate name does not disqualify a header: duplicates are renamed by
    :func:`sniff` with a warning, while a row of values cannot be repaired at
    all. Uniqueness still lowers the reported confidence, because it is real
    evidence about the file's quality.
    """
    if not rows:
        return HeaderDetection(has_header=False, fields=(), confidence=0.0)
    first = tuple(cell.strip() for cell in rows[0])
    if not first:
        return HeaderDetection(has_header=False, fields=(), confidence=0.0)
    all_named = all(bool(cell) for cell in first)
    unique = len({cell.casefold() for cell in first}) == len(first)
    free_of_values = not any(
        is_numeric_token(cell, DecimalStyle.POINT) or is_date_like_token(cell) for cell in first
    )
    score = (float(all_named) + float(unique) + float(free_of_values)) / 3.0
    return HeaderDetection(
        has_header=all_named and free_of_values,
        fields=first,
        confidence=round(score, 3),
    )


def detect_decimal_style(rows: Sequence[Sequence[str]]) -> tuple[DecimalStyle, tuple[str, ...]]:
    """Return the decimal convention the data appears to use."""
    comma_matches = 0
    point_matches = 0
    for row in rows:
        for cell in row:
            token = cell.strip()
            if not token:
                continue
            if _COMMA_DECIMAL.fullmatch(token):
                comma_matches += 1
            elif _POINT_DECIMAL.fullmatch(token):
                point_matches += 1
    if comma_matches >= _MIN_COMMA_DECIMAL_EVIDENCE and point_matches == 0:
        return DecimalStyle.COMMA, ()
    if comma_matches > 0 and point_matches > 0:
        return (
            DecimalStyle.POINT,
            (
                "Both '.' and ',' decimal separators appear in the data; '.' is "
                "assumed and the values should be checked during mapping.",
            ),
        )
    return DecimalStyle.POINT, ()


def is_date_like_token(text: str) -> bool:
    """Return whether a token looks like a date; evidence, not a parse."""
    token = text.strip()
    if not token:
        return False
    return bool(
        _ISO_DATE.fullmatch(token)
        or _ISO_MONTH.fullmatch(token)
        or _SLASHED_DATE.fullmatch(token)
        or _DAY_FIRST_DATE.fullmatch(token)
        or _MONTH_NAME_DATE.fullmatch(token)
    )


def is_numeric_token(text: str, style: DecimalStyle) -> bool:
    """Return whether a token is a number, optionally carrying a qualifier."""
    token = text.strip()
    if not token:
        return False
    for prefix in _QUALIFIER_PREFIXES:
        if token.startswith(prefix):
            token = token[len(prefix) :].strip()
            break
    if not token or not any(character.isdigit() for character in token):
        return False
    if style is DecimalStyle.COMMA and "," in token:
        token = token.replace(".", "").replace(",", ".")
        return _is_plain_number(token)
    if _POINT_DECIMAL.fullmatch(token):
        return True
    return _is_plain_number(token)


def sample_columns(
    rows: Sequence[Sequence[str]],
    fields: Sequence[str],
    *,
    style: DecimalStyle,
    sample_size: int = SNIFF_SAMPLE_ROWS,
) -> tuple[ColumnSample, ...]:
    """Return what a bounded sample of every column looks like."""
    width = len(fields)
    samples: list[list[str]] = [[] for _ in range(width)]
    non_empty = [0] * width
    numeric = [0] * width
    dates = [0] * width
    distinct: list[set[str]] = [set() for _ in range(width)]
    for row in rows[:sample_size]:
        for index in range(width):
            cell = row[index].strip() if index < len(row) else ""
            if not cell:
                continue
            non_empty[index] += 1
            if is_numeric_token(cell, style):
                numeric[index] += 1
            if is_date_like_token(cell):
                dates[index] += 1
            if len(samples[index]) < _COLUMN_SAMPLE_VALUES:
                samples[index].append(cell)
            distinct[index].add(cell)
    collected: list[ColumnSample] = []
    for index, name in enumerate(fields):
        count = non_empty[index]
        collected.append(
            ColumnSample(
                name=name,
                samples=tuple(samples[index]),
                non_empty_count=count,
                numeric_fraction=round(numeric[index] / count, 3) if count else 0.0,
                date_fraction=round(dates[index] / count, 3) if count else 0.0,
                distinct_count=len(distinct[index]),
            )
        )
    return tuple(collected)


def detect_layout(
    *,
    fields: Sequence[str],
    columns: Sequence[ColumnSample],
    has_header: bool,
) -> LayoutDetection:
    """Return the layout the column evidence supports."""
    evidence: list[str] = []
    warnings: list[str] = []
    normalized = tuple(_normalize_name(name) for name in fields)
    timestamp_columns = [column for column in columns if column.is_date_like]
    named_timestamp = [name for name in normalized if _matches_any(name, TIMESTAMP_NAME_HINTS)]
    parameter_columns = [
        column
        for column, name in zip(columns, normalized, strict=True)
        if _matches_any(name, PARAMETER_NAME_HINTS)
    ]
    value_columns = [
        column
        for column, name in zip(columns, normalized, strict=True)
        if _matches_any(name, VALUE_NAME_HINTS)
    ]
    coordinate_names = [name for name in normalized if _matches_any(name, COORDINATE_NAME_HINTS)]
    if coordinate_names:
        evidence.append(
            f"{len(coordinate_names)} column(s) look like coordinates "
            f"({', '.join(coordinate_names[:3])}) and were excluded from the value axis."
        )
    numeric_columns = [
        column
        for column, name in zip(columns, normalized, strict=True)
        if column.is_numeric
        and not _matches_any(name, COORDINATE_NAME_HINTS)
        and not column.is_date_like
    ]

    if timestamp_columns:
        evidence.append(
            f"{len(timestamp_columns)} column(s) contain date-like values "
            f"({', '.join(column.name for column in timestamp_columns[:3])})."
        )
    if named_timestamp:
        evidence.append(f"Header name(s) indicate a time column: {', '.join(named_timestamp[:3])}.")
    if parameter_columns:
        evidence.append(
            f"Header name(s) indicate a parameter column: "
            f"{', '.join(column.name for column in parameter_columns[:3])}."
        )
    if value_columns:
        evidence.append(
            f"Header name(s) indicate a value column: "
            f"{', '.join(column.name for column in value_columns[:3])}."
        )
    if numeric_columns:
        evidence.append(
            f"{len(numeric_columns)} column(s) are numeric outside coordinate and time "
            f"roles ({', '.join(column.name for column in numeric_columns[:3])})."
        )

    time_evidence = bool(timestamp_columns) or bool(named_timestamp)
    parameter_evidence = bool(parameter_columns)
    value_evidence = bool(value_columns) or bool(numeric_columns)

    if time_evidence and parameter_evidence and value_evidence:
        confidence = 0.9 if (parameter_columns and value_columns) else 0.7
        return LayoutDetection(
            layout=LayoutKind.LONG,
            confidence=confidence,
            evidence=tuple(evidence),
            warnings=(),
        )

    if time_evidence and len(numeric_columns) >= 2:
        non_role = [
            column
            for column, name in zip(columns, normalized, strict=True)
            if not _matches_any(name, TIMESTAMP_NAME_HINTS)
            and not _matches_any(name, COORDINATE_NAME_HINTS)
        ]
        ratio = len(numeric_columns) / len(non_role) if non_role else 0.0
        warnings.append(
            "The table looks wide: one axis is time and the other axis is carried "
            "by the column headers. The mapping step must confirm which axis the "
            "columns represent."
        )
        return LayoutDetection(
            layout=LayoutKind.WIDE,
            confidence=round(min(0.9, 0.5 + 0.4 * ratio), 3),
            evidence=tuple(evidence),
            warnings=tuple(warnings),
        )

    if time_evidence and len(numeric_columns) == 1 and not has_header:
        warnings.append(
            "The table has one date-like column and one numeric column; the layout "
            "cannot be decided from the data alone."
        )
        return LayoutDetection(
            layout=LayoutKind.UNKNOWN,
            confidence=0.3,
            evidence=tuple(evidence),
            warnings=tuple(warnings),
        )

    if not evidence:
        evidence.append("No time, parameter, or value column could be identified.")
    warnings.append(
        "The layout could not be determined from the data; the analyst must supply "
        "the column mapping explicitly."
    )
    return LayoutDetection(
        layout=LayoutKind.UNKNOWN,
        confidence=0.0,
        evidence=tuple(evidence),
        warnings=tuple(warnings),
    )


def sniff(
    rows: Sequence[Sequence[str]],
    *,
    file_format: FileFormat,
    encoding: str | None = None,
    delimiter: str | None = None,
    sample_truncated: bool = False,
    declared_fields: tuple[str, ...] | None = None,
) -> SniffResult:
    """Describe a table from a bounded sample of its rows.

    ``declared_fields`` is for formats that carry their schema structurally —
    a Parquet file names its columns in the footer and has no header row at
    all. When it is supplied, every sampled row is data, the fields are the
    declared ones, and header detection is skipped entirely, because deciding
    whether data looks like a header is exactly the guess this parameter
    prevents.
    """
    warnings: list[str] = []
    if sample_truncated:
        warnings.append(
            "The sample ends inside a record, so the last sampled row may be incomplete."
        )
    if declared_fields is not None:
        header = HeaderDetection(has_header=False, fields=declared_fields, confidence=1.0)
        data_rows = rows
        fields = declared_fields
        header_row_index: int | None = None
    else:
        header = detect_header(rows)
        data_rows = rows[1:] if header.has_header else rows
        width = max((len(row) for row in rows), default=0)
        if header.has_header:
            fields = _unique_fields(header.fields, width, warnings)
            header_row_index = 0
        else:
            fields = tuple(f"column_{index + 1}" for index in range(width))
            header_row_index = None
            if rows:
                warnings.append(
                    "The first row was not detected as a header; columns were named by "
                    "position and the analyst must confirm the mapping."
                )
        if width and len(header.fields) != width and header.has_header:
            warnings.append(
                "The first row has a different number of fields than a later row; the "
                "header may be incomplete."
            )
    style, style_warnings = detect_decimal_style(data_rows)
    warnings.extend(style_warnings)
    columns = sample_columns(data_rows, fields, style=style)
    layout = detect_layout(fields=fields, columns=columns, has_header=header.has_header)
    warnings.extend(layout.warnings)
    return SniffResult(
        file_format=file_format,
        encoding=encoding,
        delimiter=delimiter,
        has_header=header.has_header,
        fields=fields,
        header_row_index=header_row_index,
        decimal_style=style,
        columns=columns,
        layout=layout,
        sample_rows=tuple(tuple(row) for row in rows),
        warnings=tuple(warnings),
    )


def sniff_delimited_bytes(
    payload: bytes,
    *,
    file_format: FileFormat,
    sample_rows: int = SNIFF_SAMPLE_ROWS,
) -> SniffResult:
    """Describe a delimited file from a bounded byte sample of its content."""
    if file_format not in {FileFormat.CSV, FileFormat.TSV}:
        raise ValidationError(
            "Byte-level sniffing is only defined for delimited text files.",
            details={"file_format": file_format.value},
        )
    if b"\x00" in payload:
        raise ParsingError(
            "The file contains binary data and cannot be read as delimited text.",
            details={"reason": "binary_content"},
        )
    trimmed, truncated = _trim_to_last_newline(payload)
    encoding = detect_encoding(trimmed)
    text = _decode_sample(trimmed, encoding.encoding, truncated)
    delimiter_detection = detect_delimiter(text)
    warnings = list(encoding.warnings)
    if delimiter_detection.confidence == 0.0:
        warnings.append(
            "No delimiter produced a consistent field count; a single-column table is assumed."
        )
    rows = _read_rows(text, delimiter_detection.delimiter, sample_rows)
    if not rows:
        raise ParsingError("The file contains no rows.")
    result = sniff(
        rows,
        file_format=file_format,
        encoding=encoding.encoding,
        delimiter=delimiter_detection.delimiter,
        sample_truncated=truncated,
    )
    return SniffResult(
        file_format=result.file_format,
        encoding=result.encoding,
        delimiter=result.delimiter,
        has_header=result.has_header,
        fields=result.fields,
        header_row_index=result.header_row_index,
        decimal_style=result.decimal_style,
        columns=result.columns,
        layout=result.layout,
        sample_rows=result.sample_rows,
        warnings=tuple(warnings) + result.warnings,
    )


def _trim_to_last_newline(payload: bytes) -> tuple[bytes, bool]:
    """Trim a byte sample to its last complete line."""
    position = payload.rfind(b"\n")
    if position == -1:
        return payload, True
    return payload[: position + 1], False


def _decode_sample(payload: bytes, encoding: str, truncated: bool) -> str:
    """Decode a byte sample, tolerating a single incomplete trailing character."""
    errors = "strict" if not truncated else "ignore"
    try:
        return payload.decode(encoding, errors=errors)
    except UnicodeDecodeError as exc:
        raise ParsingError(
            "The file could not be decoded with the detected encoding.",
            details={"encoding": encoding, "reason": "undecodable_content"},
        ) from exc


def _read_rows(text: str, delimiter: str, limit: int) -> tuple[tuple[str, ...], ...]:
    """Read up to ``limit`` rows from decoded text."""
    rows: list[tuple[str, ...]] = []
    reader = csv.reader(io.StringIO(text), delimiter=delimiter, quotechar=_QUOTE_CHAR)
    try:
        for row in reader:
            if not row or all(not cell.strip() for cell in row):
                continue
            rows.append(tuple(row))
            if len(rows) >= limit:
                break
    except csv.Error as exc:
        raise ParsingError(
            "The delimited file could not be split into records.",
            details={"reason": "invalid_record", "rows_read": len(rows)},
        ) from exc
    return tuple(rows)


def _unique_fields(fields: Sequence[str], width: int, warnings: list[str]) -> tuple[str, ...]:
    """Return field names that are non-empty and unique."""
    resolved: list[str] = []
    seen: Counter[str] = Counter()
    for index in range(width):
        raw = fields[index].strip() if index < len(fields) else ""
        name = raw or f"column_{index + 1}"
        if not raw:
            warnings.append(
                f"The header of column {index + 1} is empty; the column was named '{name}'."
            )
        seen[name.casefold()] += 1
        if seen[name.casefold()] > 1:
            name = f"{name}_{seen[name.casefold()]}"
            warnings.append(
                f"The header '{raw or name}' appears more than once; the duplicate "
                f"was renamed to '{name}'."
            )
        resolved.append(name)
    if len(resolved) < width:
        warnings.append("The header has fewer names than the widest row.")
    return tuple(resolved)


def _normalize_name(name: str) -> str:
    """Normalize a header name for hint matching."""
    lowered = name.strip().casefold()
    normalized = re.sub(r"[^0-9a-z]+", "_", lowered)
    return normalized.strip("_")


def normalize_header_name(name: str) -> str:
    """Return the normalized form of a header name for hint matching.

    Matching collapses case and non-alphanumeric characters so that
    ``Sample Date``, ``sample_date``, and ``SAMPLE-DATE`` all propose the same
    role. The function is public because the mapping module must apply exactly
    the same normalization when it proposes roles from header names.
    """
    return _normalize_name(name)


def _matches_any(name: str, hints: Sequence[str]) -> bool:
    """Return whether a normalized name contains any of the hints."""
    return any(hint in name for hint in hints)


def _is_plain_number(token: str) -> bool:
    """Return whether a token is a plain number without unit text."""
    return bool(_PLAIN_NUMBER.fullmatch(token))
