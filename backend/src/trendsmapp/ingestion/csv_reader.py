"""PyArrow-based chunked CSV/TSV reader with explicit parse options.

Every cell is read as text. Type inference is disabled on purpose: a reader
that parses ``"1,5"`` or ``"<0.01"`` into a number would destroy the raw value
that the canonical observation model must preserve, and it would decide the
decimal convention before the analyst has seen the file. The reader therefore
has no opinion about scientific meaning at all.

The reader executes options the sniffer produced and never guesses: column
names, the delimiter, the encoding, and the number of leading rows to skip are
all supplied by the caller.
"""

from __future__ import annotations

import codecs
import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import BinaryIO, Final

import pyarrow as pa
import pyarrow.csv as pa_csv

from trendsmapp.constants import CSV_RECORD_BATCH_ROWS
from trendsmapp.errors import ParsingError, ValidationError
from trendsmapp.ingestion.chunking import TextBatch

__all__ = [
    "CsvReadOptions",
    "count_csv_rows",
    "read_csv_batches",
]

#: The smallest block PyArrow may read at once.
MIN_BLOCK_BYTES: Final[int] = 64 * 1024

#: The largest block PyArrow may read at once.
MAX_BLOCK_BYTES: Final[int] = 64 * 1024 * 1024

#: Encodings that PyArrow understands directly, without transcoding.
_DIRECT_ENCODINGS: Final[frozenset[str]] = frozenset({"utf-8", "utf8", "utf-8-sig", "ascii"})

_FIELD_COUNT_PATTERN: Final[re.Pattern[str]] = re.compile(r"Expected (\d+) columns, got (\d+)")


@dataclass(frozen=True, slots=True)
class CsvReadOptions:
    """The exact options a delimited file is read with."""

    column_names: tuple[str, ...]
    delimiter: str
    quote_char: str = '"'
    encoding: str = "utf-8"
    skip_leading_rows: int = 0
    batch_rows: int = CSV_RECORD_BATCH_ROWS
    block_bytes: int = 4 * 1024 * 1024

    def __post_init__(self) -> None:
        if not self.column_names:
            raise ValidationError("A delimited read requires the column names.")
        if not all(name.strip() for name in self.column_names):
            raise ValidationError("Column names must not be empty.")
        if len(set(self.column_names)) != len(self.column_names):
            raise ValidationError("Column names must be unique.")
        if len(self.delimiter) != 1:
            raise ValidationError(
                "The delimiter must be exactly one character.",
                details={"delimiter": self.delimiter},
            )
        if len(self.quote_char) != 1:
            raise ValidationError("The quote character must be exactly one character.")
        if self.skip_leading_rows < 0:
            raise ValidationError("The number of skipped rows cannot be negative.")
        if self.batch_rows < 1:
            raise ValidationError("The batch size must be at least one row.")
        if not MIN_BLOCK_BYTES <= self.block_bytes <= MAX_BLOCK_BYTES:
            raise ValidationError(
                "The read block size is outside the accepted range.",
                details={
                    "block_bytes": self.block_bytes,
                    "minimum_bytes": MIN_BLOCK_BYTES,
                    "maximum_bytes": MAX_BLOCK_BYTES,
                },
            )


def read_csv_batches(stream: BinaryIO, options: CsvReadOptions) -> Iterator[TextBatch]:
    """Yield text batches of a delimited file.

    The stream must be positioned at the beginning of the file. Rows keep their
    physical order because the reader is single-threaded by construction.
    """
    source: BinaryIO
    if options.encoding in _DIRECT_ENCODINGS:
        source = stream
    else:
        source = _TranscodingStream(stream, options.encoding)  # type: ignore[assignment]

    read_options = pa_csv.ReadOptions(
        use_threads=False,
        block_size=options.block_bytes,
        skip_rows=options.skip_leading_rows,
        column_names=list(options.column_names),
        autogenerate_column_names=False,
    )
    parse_options = pa_csv.ParseOptions(
        delimiter=options.delimiter,
        quote_char=options.quote_char,
        double_quote=True,
        escape_char=False,
        newlines_in_values=True,
    )
    convert_options = pa_csv.ConvertOptions(
        column_types={name: pa.string() for name in options.column_names},
        null_values=[],
        strings_can_be_null=False,
    )

    rows_emitted = 0
    pending: list[tuple[str, ...]] = []
    try:
        reader = pa_csv.open_csv(
            source,
            read_options=read_options,
            parse_options=parse_options,
            convert_options=convert_options,
        )
        for batch in reader:
            resolved = _batch_to_text(batch, options.column_names)
            if resolved is None:
                continue
            for row in resolved:
                pending.append(row)
                if len(pending) < options.batch_rows:
                    continue
                chunk = tuple(pending)
                pending.clear()
                yield TextBatch(
                    columns=options.column_names,
                    rows=chunk,
                    missing=tuple(tuple(not cell for cell in row) for row in chunk),
                    first_row_index=rows_emitted,
                )
                rows_emitted += len(chunk)
        if pending:
            chunk = tuple(pending)
            pending.clear()
            yield TextBatch(
                columns=options.column_names,
                rows=chunk,
                missing=tuple(tuple(not cell for cell in row) for row in chunk),
                first_row_index=rows_emitted,
            )
            rows_emitted += len(chunk)
    except pa.ArrowInvalid as exc:
        raise _translate_csv_error(
            exc, rows_emitted=rows_emitted, columns=len(options.column_names)
        ) from exc
    except pa.ArrowNotImplementedError as exc:
        raise ParsingError(
            "The delimited file uses a feature this reader does not support.",
            details={"reason": "unsupported_feature", "rows_read": rows_emitted},
        ) from exc
    except pa.ArrowTypeError as exc:
        raise ParsingError(
            "The delimited file could not be read as text.",
            details={"reason": "unreadable_text", "rows_read": rows_emitted},
        ) from exc


def count_csv_rows(stream: BinaryIO, options: CsvReadOptions) -> int:
    """Return the number of data rows in a delimited file."""
    return sum(batch.row_count for batch in read_csv_batches(stream, options))


def _batch_to_text(
    batch: pa.RecordBatch, column_names: tuple[str, ...]
) -> tuple[tuple[str, ...], ...] | None:
    """Convert one Arrow batch into rows of exact text."""
    if batch.num_rows == 0:
        return None
    if batch.num_columns != len(column_names):
        raise ParsingError(
            "The delimited file produced a record with an unexpected number of fields.",
            details={"expected_columns": len(column_names), "found_columns": batch.num_columns},
        )
    columns = [batch.column(index).to_pylist() for index in range(batch.num_columns)]
    return tuple(
        tuple("" if value is None else str(value) for value in values)
        for values in zip(*columns, strict=True)
    )


def _translate_csv_error(
    error: pa.ArrowInvalid, *, rows_emitted: int, columns: int
) -> ParsingError:
    """Translate a PyArrow parse failure into a sanitized parsing error.

    The message from the underlying library can contain a fragment of the
    offending record. An error message is allowed to describe the failure; it
    is not allowed to echo file content, so only the structural counts and the
    row range are carried over.
    """
    message = str(error)
    if "empty csv" in message.lower():
        return ParsingError(
            "The file contains no records.",
            details={"reason": "empty_table"},
        )
    if "Expected" in message and "columns" in message:
        counts = _column_counts(message)
        if counts is not None:
            expected, found = counts
            return ParsingError(
                "The delimited file is not a table: at or after data row "
                f"{rows_emitted + 1} a record has {found} fields while the table has "
                f"{expected}.",
                details={
                    "reason": "inconsistent_field_count",
                    "expected_columns": expected,
                    "found_columns": found,
                    "row_from": rows_emitted + 1,
                    "declared_columns": columns,
                },
            )
    if "quote" in message.lower():
        return ParsingError(
            "The delimited file contains an unterminated quoted field at or after "
            f"data row {rows_emitted + 1}.",
            details={"reason": "unterminated_quote", "row_from": rows_emitted + 1},
        )
    if "utf8" in message.lower() or "utf-8" in message.lower():
        return ParsingError(
            f"The delimited file is not valid UTF-8 at or after data row {rows_emitted + 1}.",
            details={"reason": "invalid_encoding", "row_from": rows_emitted + 1},
        )
    return ParsingError(
        f"The delimited file could not be parsed at or after data row {rows_emitted + 1}.",
        details={"reason": "unparsable_record", "row_from": rows_emitted + 1},
    )


def _column_counts(message: str) -> tuple[int, int] | None:
    """Extract the expected and found field counts from a PyArrow message."""
    match = _FIELD_COUNT_PATTERN.search(message)
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


class _TranscodingStream:
    """A read-only adaptor that decodes a byte stream into UTF-8.

    Only the readers need this: PyArrow expects UTF-8 input, and a delimited
    file that the sniffer decoded as Windows-1252 must be transcoded before it
    reaches the parser. The decoder is incremental so that a multi-byte
    character split across two reads is still decoded exactly once.
    """

    def __init__(self, stream: BinaryIO, encoding: str, *, chunk_bytes: int = 1024 * 1024) -> None:
        self._stream = stream
        self._encoding = encoding
        self._chunk_bytes = chunk_bytes
        self._decoder = codecs.getincrementaldecoder(encoding)("strict")
        self._buffer = bytearray()
        self._exhausted = False
        self._closed = False

    def read(self, size: int = -1) -> bytes:
        """Return up to ``size`` UTF-8 bytes, or everything that remains."""
        if self._closed:
            raise ValueError("The stream is closed.")
        while not self._exhausted and (size < 0 or len(self._buffer) < size):
            raw = self._stream.read(self._chunk_bytes)
            if not raw:
                self._exhausted = True
                try:
                    tail = self._decoder.decode(b"", final=True)
                except UnicodeDecodeError as exc:
                    raise ParsingError(
                        "The file ends inside a multi-byte character.",
                        details={"encoding": self._encoding, "reason": "truncated_character"},
                    ) from exc
                self._buffer.extend(tail.encode("utf-8"))
                break
            try:
                decoded = self._decoder.decode(raw)
            except UnicodeDecodeError as exc:
                raise ParsingError(
                    "The file does not match the detected encoding.",
                    details={"encoding": self._encoding, "reason": "invalid_byte_sequence"},
                ) from exc
            self._buffer.extend(decoded.encode("utf-8"))
        if size < 0:
            data = bytes(self._buffer)
            self._buffer.clear()
            return data
        data = bytes(self._buffer[:size])
        del self._buffer[:size]
        return data

    def readable(self) -> bool:
        """Return whether the stream can be read."""
        return True

    def seekable(self) -> bool:
        """Return whether the stream can be rewound; transcoding cannot."""
        return False

    @property
    def closed(self) -> bool:
        """Return whether the stream was closed."""
        return self._closed

    def close(self) -> None:
        """Close the stream and the underlying source."""
        self._closed = True
        self._buffer.clear()
        self._stream.close()
