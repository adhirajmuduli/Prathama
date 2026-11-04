"""Deterministic conversion of wide sheets to canonical long rows.

A station-by-time matrix stores one observation per *cell*; the canonical
observation model stores one observation per *row*. The conversion is a pure
reshape: every cell of a mapped value column becomes one long record that
carries the row's timestamp, the column's station and parameter labels, and the
physical row it came from.

Nothing is inferred here. Which column holds which station, which parameter the
table represents, and what unit applies are all answers the confirmed column
mapping already states. The converter therefore cannot guess: it reshapes
exactly what the mapping says, and leaves every other cell of the row behind.

The output schema is fixed and shared with the parser, so normalization
receives one shape no matter which format or layout produced it.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from trendsmapp.domain.enums import ColumnRole
from trendsmapp.ingestion.chunking import TextBatch
from trendsmapp.ingestion.column_mapping import ResolvedMapping

__all__ = [
    "LONG_SCHEMA_FIELDS",
    "WideConversionStats",
    "WideToLongIterator",
    "long_schema_columns",
]

#: The canonical long schema every parser produces and normalization consumes.
#: The order is fixed: a stored dataset can be traced to a schema version, and
#: a reader of the Parquet artifact can rely on this column order.
LONG_SCHEMA_FIELDS: tuple[str, ...] = (
    "station",
    "sampled_at",
    "parameter",
    "value",
    "unit",
    "qualifier",
    "latitude",
    "longitude",
    "depth_m",
    "sector",
    "source_row",
    "source_sheet",
)


def long_schema_columns() -> tuple[str, ...]:
    """Return the canonical long schema columns."""
    return LONG_SCHEMA_FIELDS


@dataclass(frozen=True, slots=True)
class WideConversionStats:
    """What one conversion pass did, for the parse report."""

    records_emitted: int
    source_rows_seen: int
    source_rows_skipped: int


class WideToLongIterator:
    """Streams wide batches through the mapping into canonical long batches."""

    def __init__(
        self,
        *,
        batches: Iterator[TextBatch],
        resolved: ResolvedMapping,
        source_sheet: str,
        batch_rows: int,
    ) -> None:
        self._batches = batches
        self._resolved = resolved
        self._source_sheet = source_sheet
        self._batch_rows = batch_rows
        self._pending_rows: list[tuple[str, ...]] = []
        self._pending_missing: list[tuple[bool, ...]] = []
        self._source_exhausted = False
        self.records_emitted = 0
        self.source_rows_seen = 0
        self.source_rows_skipped = 0

    @property
    def stats(self) -> WideConversionStats:
        """Return the conversion counters collected so far."""
        return WideConversionStats(
            records_emitted=self.records_emitted,
            source_rows_seen=self.source_rows_seen,
            source_rows_skipped=self.source_rows_skipped,
        )

    def __iter__(self) -> WideToLongIterator:
        return self

    def __next__(self) -> TextBatch:
        """Return the next long batch, buffering across source batches.

        One source batch converts to ``columns per row`` long records, which
        rarely aligns with the requested output batch size, so converted
        records are buffered and emitted in exact slices until the source is
        exhausted. No record is ever dropped at a batch boundary.
        """
        while len(self._pending_rows) < self._batch_rows and not self._source_exhausted:
            try:
                batch = next(self._batches)
            except StopIteration:
                self._source_exhausted = True
                break
            converted_rows, converted_missing = self._convert_batch(batch)
            self._pending_rows.extend(converted_rows)
            self._pending_missing.extend(converted_missing)
        if not self._pending_rows:
            raise StopIteration
        chunk_rows = tuple(self._pending_rows[: self._batch_rows])
        chunk_missing = tuple(self._pending_missing[: self._batch_rows])
        del self._pending_rows[: self._batch_rows]
        del self._pending_missing[: self._batch_rows]
        first_row_index = self.records_emitted
        self.records_emitted += len(chunk_rows)
        return TextBatch(
            columns=LONG_SCHEMA_FIELDS,
            rows=chunk_rows,
            missing=chunk_missing,
            first_row_index=first_row_index,
        )

    def _convert_batch(
        self, batch: TextBatch
    ) -> tuple[list[tuple[str, ...]], list[tuple[bool, ...]]]:
        """Convert one wide batch into long records.

        The physical row number counts from one and includes every leading
        row, so a record's ``source_row`` matches the row number the analyst
        sees in the spreadsheet application.
        """
        columns = batch.columns
        resolved = self._resolved
        mapping = resolved.mapping
        timestamp_field = resolved.field_of_role(ColumnRole.TIMESTAMP)
        if timestamp_field is None:
            raise ValueError("A wide mapping requires a timestamp column.")
        time_index = columns.index(timestamp_field)
        station_field = resolved.field_of_role(ColumnRole.STATION)
        station_index = columns.index(station_field) if station_field else None

        value_plans: list[tuple[int, str | None, str | None, str | None]] = []
        for mapped in resolved.wide_value_columns:
            value_plans.append(
                (
                    columns.index(mapped.column),
                    mapped.station_label,
                    mapped.parameter_label or mapping.default_parameter,
                    mapped.unit or mapping.default_unit,
                )
            )

        rows: list[tuple[str, ...]] = []
        missing: list[tuple[bool, ...]] = []
        for offset, wide_row in enumerate(batch.rows):
            wide_missing = batch.missing[offset]
            physical_row = resolved.long_row_offset + batch.first_row_index + offset
            self.source_rows_seen += 1
            sampled_at = wide_row[time_index]
            station_from_column = wide_row[station_index] if station_index is not None else ""
            empty_values = all(wide_row[index] == "" for index, _, _, _ in value_plans)
            if sampled_at == "" and empty_values:
                self.source_rows_skipped += 1
                continue
            for index, station_label, parameter_label, unit in value_plans:
                value = wide_row[index]
                station = station_label or station_from_column
                parameter = parameter_label or ""
                latitude_index = _optional_index(columns, "latitude")
                longitude_index = _optional_index(columns, "longitude")
                rows.append(
                    (
                        station,
                        sampled_at,
                        parameter,
                        value,
                        unit or "",
                        "",
                        wide_row[latitude_index] if latitude_index is not None else "",
                        wide_row[longitude_index] if longitude_index is not None else "",
                        "",
                        "",
                        str(physical_row),
                        self._source_sheet,
                    )
                )
                missing.append(
                    (
                        station == "",
                        sampled_at == "",
                        parameter == "",
                        value == "",
                        unit is None or unit == "",
                        True,
                        (wide_missing[latitude_index] if latitude_index is not None else True),
                        (wide_missing[longitude_index] if longitude_index is not None else True),
                        True,
                        True,
                        False,
                        self._source_sheet == "",
                    )
                )
        return rows, missing


def _optional_index(columns: tuple[str, ...], name: str) -> int | None:
    """Return the index of an optional wide column, when present."""
    try:
        return columns.index(name)
    except ValueError:
        return None
