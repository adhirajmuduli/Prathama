"""The normalization pipeline: parse output to canonical observations and Parquet.

The pipeline ties the pieces together: it converts long-schema batches into
normalized rows, canonicalizes each row, detects duplicates under the declared
policy, and writes the canonical dataset as a deterministic Parquet artifact.
Every input row is accounted for in the report — as an observation, as a
duplicate, or as a skipped row with a coded reason.
"""

from __future__ import annotations

import dataclasses
import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO, Final

import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import BaseModel, ConfigDict, Field

from trendsmapp.constants import DEFAULT_ANALYSIS_CRS
from trendsmapp.contracts.versions import APPLICATION_VERSION, ARTIFACT_SCHEMA_VERSION
from trendsmapp.domain.enums import DuplicatePolicy, QcFlagCode, QcStatus
from trendsmapp.domain.models import Observation
from trendsmapp.domain.policies import DuplicatePolicySpec
from trendsmapp.domain.units import get_unit_registry
from trendsmapp.ingestion.chunking import TextBatch
from trendsmapp.ingestion.column_mapping import ColumnMapping
from trendsmapp.ingestion.sniffing import DecimalStyle
from trendsmapp.normalization.canonicalize import (
    CanonicalizationResult,
    NormalizedRow,
    SkippedRow,
    canonicalize_row,
    derive_station_key,
)
from trendsmapp.normalization.coordinates import CoordinateResult
from trendsmapp.normalization.duplicates import find_duplicates
from trendsmapp.normalization.parameters import get_parameter_registry

__all__ = [
    "CANONICAL_PARQUET_SCHEMA",
    "MAX_RECORDED_SKIPPED_ROWS",
    "MAX_SORT_IN_MEMORY_ROWS",
    "NormalizationPipeline",
    "NormalizationReport",
    "NormalizationResult",
    "ParquetArtifact",
    "write_canonical_parquet",
]

#: Rows above this count are written in stream order and the report says so.
MAX_SORT_IN_MEMORY_ROWS: Final[int] = 1_000_000

#: How many skipped rows are recorded verbatim in the report; the rest are
#: counted. The raw rows are always preserved in the raw artifact.
MAX_RECORDED_SKIPPED_ROWS: Final[int] = 1_000

#: The deterministic sort key of the canonical dataset.
SORT_KEY: Final[tuple[str, ...]] = ("sampled_at", "station_id", "parameter_id", "source_row")


class NormalizationReport(BaseModel):
    """The stored document describing one normalization run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = ARTIFACT_SCHEMA_VERSION
    application_version: str = APPLICATION_VERSION
    dataset_id: str
    dataset_version_id: str
    mapping: ColumnMapping
    row_count: int = 0
    observation_count: int = 0
    skipped_count: int = 0
    skipped_rows: tuple[SkippedRow, ...] = ()
    issue_counts: dict[str, int] = Field(default_factory=dict)
    unknown_parameters: int = 0
    unit_conversions: int = 0
    unit_case_corrections: int = 0
    duplicate_groups: int = 0
    duplicate_rows_flagged: int = 0
    sorted: bool = True
    sort_key: tuple[str, ...] = SORT_KEY
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class NormalizationResult:
    """The outcome of one pipeline run."""

    observations: tuple[Observation, ...]
    report: NormalizationReport


@dataclass(frozen=True, slots=True)
class ParquetArtifact:
    """A written canonical Parquet artifact."""

    sha256: str
    size_bytes: int
    row_count: int
    path: str | None


#: The fixed Arrow schema of the canonical dataset.
CANONICAL_PARQUET_SCHEMA: Final[pa.Schema] = pa.schema(
    [
        pa.field("observation_id", pa.string(), nullable=False),
        pa.field("dataset_id", pa.string(), nullable=False),
        pa.field("dataset_version_id", pa.string(), nullable=False),
        pa.field("source_row", pa.int64(), nullable=False),
        pa.field("source_sheet", pa.string()),
        pa.field("station_id", pa.string(), nullable=False),
        pa.field("station_label", pa.string()),
        pa.field("latitude_wgs84", pa.float64(), nullable=False),
        pa.field("longitude_wgs84", pa.float64(), nullable=False),
        pa.field("x_projected_m", pa.float64()),
        pa.field("y_projected_m", pa.float64()),
        pa.field("source_crs", pa.string(), nullable=False),
        pa.field("analysis_crs", pa.string(), nullable=False),
        pa.field("sector", pa.string()),
        pa.field("sampled_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("sampling_depth_m", pa.float64()),
        pa.field("parameter_id", pa.string(), nullable=False),
        pa.field("parameter_label", pa.string(), nullable=False),
        pa.field("raw_value", pa.string()),
        pa.field("raw_unit", pa.string()),
        pa.field("value_qualifier", pa.string(), nullable=False),
        pa.field("canonical_value", pa.float64()),
        pa.field("canonical_unit", pa.string()),
        pa.field("detection_limit", pa.float64()),
        pa.field("conversion_factor", pa.float64()),
        pa.field("qc_status", pa.string(), nullable=False),
        pa.field("qc_flags", pa.list_(pa.string()), nullable=False),
        pa.field("is_excluded", pa.bool_(), nullable=False),
        pa.field("exclusion_reason", pa.string()),
        pa.field("provenance_ids", pa.list_(pa.string()), nullable=False),
    ]
)


def _observation_to_record(observation: Observation) -> dict[str, Any]:
    """Return the Parquet record of one canonical observation."""
    return {
        "observation_id": observation.observation_id,
        "dataset_id": observation.dataset_id,
        "dataset_version_id": observation.dataset_version_id,
        "source_row": observation.source_row,
        "source_sheet": observation.source_sheet,
        "station_id": observation.station_id,
        "station_label": observation.station_label,
        "latitude_wgs84": observation.latitude_wgs84,
        "longitude_wgs84": observation.longitude_wgs84,
        "x_projected_m": observation.x_projected_m,
        "y_projected_m": observation.y_projected_m,
        "source_crs": observation.source_crs,
        "analysis_crs": observation.analysis_crs,
        "sector": observation.sector,
        "sampled_at": observation.sampled_at,
        "sampling_depth_m": observation.sampling_depth_m,
        "parameter_id": observation.parameter_id,
        "parameter_label": observation.parameter_label,
        "raw_value": (
            observation.raw_value
            if isinstance(observation.raw_value, str)
            else repr(observation.raw_value)
            if observation.raw_value is not None
            else None
        ),
        "raw_unit": observation.raw_unit,
        "value_qualifier": observation.value_qualifier.value,
        "canonical_value": observation.canonical_value,
        "canonical_unit": observation.canonical_unit,
        "detection_limit": observation.detection_limit,
        "conversion_factor": observation.conversion_factor,
        "qc_status": observation.qc_status.value,
        "qc_flags": [flag.value for flag in observation.qc_flags],
        "is_excluded": observation.is_excluded,
        "exclusion_reason": observation.exclusion_reason,
        "provenance_ids": list(observation.provenance_ids),
    }


def write_canonical_parquet(
    observations: Sequence[Observation],
    destination: BinaryIO | Path,
    *,
    dataset_id: str,
    dataset_version_id: str,
    sorted_rows: bool = True,
) -> ParquetArtifact:
    """Write canonical observations as a deterministic Parquet artifact.

    Rows are sorted by :data:`SORT_KEY` when the count allows it in memory;
    otherwise they are written in stream order and the caller records
    ``sorted=False``. The file carries the schema version, application version,
    and dataset identity in its metadata, and no timestamps, so the same rows
    always produce the same bytes.
    """
    rows = list(observations)
    if sorted_rows and len(rows) <= MAX_SORT_IN_MEMORY_ROWS:
        rows.sort(
            key=lambda observation: (
                observation.sampled_at,
                observation.station_id,
                observation.parameter_id,
                observation.source_row,
            )
        )
    records = [_observation_to_record(observation) for observation in rows]
    table = pa.Table.from_pylist(records, schema=CANONICAL_PARQUET_SCHEMA)
    metadata = {
        b"schema_version": ARTIFACT_SCHEMA_VERSION.encode(),
        b"application_version": APPLICATION_VERSION.encode(),
        b"dataset_id": dataset_id.encode(),
        b"dataset_version_id": dataset_version_id.encode(),
        b"row_count": str(len(rows)).encode(),
        b"sort_key": ",".join(SORT_KEY).encode(),
        b"sorted": b"true" if sorted_rows and len(rows) <= MAX_SORT_IN_MEMORY_ROWS else b"false",
    }
    schema = table.schema.with_metadata(metadata)
    table = table.cast(schema)
    if isinstance(destination, Path):
        with destination.open("wb") as handle:
            pq.write_table(table, handle, compression="snappy", version="2.6")
        payload = destination.read_bytes()
        path: str | None = str(destination)
    else:
        pq.write_table(table, destination, compression="snappy", version="2.6")
        destination.seek(0)
        payload = destination.read()
        path = None
    return ParquetArtifact(
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
        row_count=len(rows),
        path=path,
    )


class NormalizationPipeline:
    """Runs canonicalization over parsed batches and produces the report."""

    def __init__(
        self,
        *,
        mapping: ColumnMapping,
        dataset_id: str,
        dataset_version_id: str,
        decimal_style: DecimalStyle = DecimalStyle.POINT,
        analysis_crs: str = DEFAULT_ANALYSIS_CRS,
        duplicate_policy: DuplicatePolicy = DuplicatePolicy.FLAG_ALL,
        station_coordinates: dict[str, CoordinateResult] | None = None,
    ) -> None:
        self._mapping = mapping
        self._dataset_id = dataset_id
        self._dataset_version_id = dataset_version_id
        self._decimal_style = decimal_style
        self._analysis_crs = analysis_crs
        self._duplicate_policy = DuplicatePolicySpec(policy=duplicate_policy)
        self._station_coordinates = station_coordinates or {}

    def run(self, batches: Iterable[TextBatch]) -> NormalizationResult:
        """Canonicalize every row of every batch and build the report."""
        results: list[CanonicalizationResult] = []
        row_count = 0
        for batch in batches:
            for row in NormalizedRow.from_batch(batch):
                row_count += 1
                results.append(
                    canonicalize_row(
                        row,
                        mapping=self._mapping,
                        dataset_id=self._dataset_id,
                        dataset_version_id=self._dataset_version_id,
                        decimal_style=self._decimal_style,
                        analysis_crs=self._analysis_crs,
                        parameter_registry=get_parameter_registry(),
                        unit_registry=get_unit_registry(),
                        station_coordinates=self._station_coordinates,
                    )
                )

        observations = [result.observation for result in results if result.observation is not None]
        skipped = [result.skipped for result in results if result.skipped is not None]
        issues = [issue for result in results for issue in result.issues]

        issue_counts: dict[str, int] = {}
        for issue in issues:
            issue_counts[issue.code] = issue_counts.get(issue.code, 0) + 1

        duplicate_report = self._apply_duplicates(observations, results)

        warnings: list[str] = []
        if len(observations) > MAX_SORT_IN_MEMORY_ROWS:
            warnings.append(
                f"{len(observations)} observations exceed the in-memory sort cap "
                f"({MAX_SORT_IN_MEMORY_ROWS}); the artifact is written in stream order"
            )
        if len(skipped) > MAX_RECORDED_SKIPPED_ROWS:
            warnings.append(
                f"{len(skipped)} rows were skipped; only the first "
                f"{MAX_RECORDED_SKIPPED_ROWS} are recorded in this report"
            )

        report = NormalizationReport(
            dataset_id=self._dataset_id,
            dataset_version_id=self._dataset_version_id,
            mapping=self._mapping,
            row_count=row_count,
            observation_count=len(observations),
            skipped_count=len(skipped),
            skipped_rows=tuple(skipped[:MAX_RECORDED_SKIPPED_ROWS]),
            issue_counts=issue_counts,
            unknown_parameters=issue_counts.get(QcFlagCode.UNKNOWN_PARAMETER.value, 0),
            unit_conversions=sum(
                1
                for result in results
                if result.observation is not None and result.observation.canonical_value is not None
            ),
            unit_case_corrections=issue_counts.get("unit_conversion", 0),
            duplicate_groups=len(duplicate_report.groups),
            duplicate_rows_flagged=len(duplicate_report.duplicate_row_indexes),
            sorted=len(observations) <= MAX_SORT_IN_MEMORY_ROWS,
            warnings=tuple(warnings),
        )
        return NormalizationResult(observations=tuple(observations), report=report)

    def _apply_duplicates(
        self, observations: list[Observation], results: list[CanonicalizationResult]
    ) -> Any:
        """Detect duplicates and flag every non-retained observation."""
        del results  # observations already exclude skipped rows
        entries: list[tuple[tuple[str, str, datetime], int, int]] = []
        for observation_index, observation in enumerate(observations):
            key = (
                derive_station_key(observation.station_label or ""),
                observation.parameter_id,
                observation.sampled_at,
            )
            completeness = sum(
                [
                    value is not None
                    for value in (
                        observation.canonical_value,
                        observation.canonical_unit,
                        observation.sampling_depth_m,
                        observation.sector,
                        observation.x_projected_m,
                    )
                ]
            )
            entries.append((key, observation_index, completeness))
        report = find_duplicates(entries, policy=self._duplicate_policy)
        flagged = report.duplicate_row_indexes
        if flagged:
            rebuilt: list[Observation] = []
            for observation_index, observation in enumerate(observations):
                if observation_index in flagged:
                    observation = _with_flag(observation, QcFlagCode.DUPLICATE_OBSERVATION)
                rebuilt.append(observation)
            observations[:] = rebuilt
        return report


def _with_flag(observation: Observation, flag: QcFlagCode) -> Observation:
    """Return a copy of an observation with one more QC flag."""
    return dataclasses.replace(
        observation,
        qc_flags=(*tuple(observation.qc_flags), flag),
        qc_status=QcStatus.WARNING,
    )
