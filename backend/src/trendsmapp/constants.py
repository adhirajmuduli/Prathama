"""Non-secret limits, supported formats, chunk bounds, and numerical tolerances.

Every value here is a safety ceiling or a tolerance that must behave
identically across processes. Runtime-configurable limits live in
:mod:`trendsmapp.settings`; the values below are the hard upper bounds that a
configuration may not exceed.
"""

from __future__ import annotations

from typing import Final

__all__ = [
    "ALLOWED_UPLOAD_EXTENSIONS",
    "API_MAJOR_VERSION",
    "CHUNK_SIZE_BOUNDS_BYTES",
    "CSV_RECORD_BATCH_ROWS",
    "DEFAULT_ANALYSIS_CRS",
    "DEFAULT_UPLOAD_CHUNK_BYTES",
    "GEOSPATIAL_TOLERANCES",
    "GRID_CELL_LIMITS",
    "MAX_ANIMATION_FRAMES",
    "MAX_CANDIDATE_MODELS",
    "MAX_DECOMPRESSION_RATIO",
    "MAX_EXPORT_BUNDLE_BYTES",
    "MAX_FILE_SIZE_BYTES",
    "MAX_INGESTED_COLUMNS",
    "MAX_INGESTED_ROWS",
    "MAX_SEARCH_TRIALS_PER_MODEL",
    "MAX_SHAP_ROWS",
    "MAX_UNIQUE_TIMESTAMPS_PER_RUN",
    "MAX_WORKBOOK_CELLS",
    "MAX_WORKBOOK_SHEETS",
    "MAX_WORKBOOK_UNCOMPRESSED_BYTES",
    "MAX_ZIP_MEMBERS",
    "MIN_COMPRESSION_RATIO_CHECK_BYTES",
    "PREVIEW_ROW_LIMIT",
    "SNIFF_SAMPLE_ROWS",
    "SUPPORTED_MIME_TYPES",
    "SUPPORTED_SCHEMA_VERSIONS",
]

API_MAJOR_VERSION: Final[int] = 1

#: Extensions accepted by the ingestion layer. Legacy ``.xls`` is excluded
#: because it needs a binary parser that is not part of the first release.
ALLOWED_UPLOAD_EXTENSIONS: Final[frozenset[str]] = frozenset({".csv", ".tsv", ".xlsx", ".parquet"})

#: MIME types accepted for the corresponding extensions.
SUPPORTED_MIME_TYPES: Final[dict[str, frozenset[str]]] = {
    ".csv": frozenset({"text/csv", "application/csv", "text/plain", "application/vnd.ms-excel"}),
    ".tsv": frozenset({"text/tab-separated-values", "text/plain", "application/vnd.ms-excel"}),
    ".xlsx": frozenset(
        {
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/octet-stream",
            "application/zip",
        }
    ),
    ".parquet": frozenset({"application/vnd.apache.parquet", "application/octet-stream"}),
}

#: Hard ceiling for an uploaded file: 100 MiB.
MAX_FILE_SIZE_BYTES: Final[int] = 100 * 1024 * 1024

#: Browser upload chunk size and the accepted range for a negotiated chunk.
DEFAULT_UPLOAD_CHUNK_BYTES: Final[int] = 5 * 1024 * 1024
CHUNK_SIZE_BOUNDS_BYTES: Final[tuple[int, int]] = (1024 * 1024, 16 * 1024 * 1024)

#: Rows per Arrow record batch while streaming delimited files.
CSV_RECORD_BATCH_ROWS: Final[int] = 50_000

#: Rows returned by the dataset preview endpoint.
PREVIEW_ROW_LIMIT: Final[int] = 200

#: Rows inspected while sniffing encoding, delimiter, header, and layout.
SNIFF_SAMPLE_ROWS: Final[int] = 200

#: Ingestion ceilings: a table above either value is rejected, never truncated.
MAX_INGESTED_ROWS: Final[int] = 5_000_000
MAX_INGESTED_COLUMNS: Final[int] = 2_000

#: Workbook defenses for untrusted ``.xlsx`` uploads.
MAX_WORKBOOK_SHEETS: Final[int] = 20
MAX_WORKBOOK_CELLS: Final[int] = 5_000_000

#: Archive defenses applied to the ZIP container inside an ``.xlsx`` file.
#: The uncompressed ceiling is separate from the cell ceiling because a small
#: archive can expand to an arbitrarily large payload before a parser sees it.
MAX_ZIP_MEMBERS: Final[int] = 5_000
MAX_WORKBOOK_UNCOMPRESSED_BYTES: Final[int] = 512 * 1024 * 1024

#: A member larger than this is rejected when its compression ratio exceeds
#: :data:`MAX_DECOMPRESSION_RATIO`. Small members are exempt because XML parts
#: legitimately compress well without being a decompression bomb.
MIN_COMPRESSION_RATIO_CHECK_BYTES: Final[int] = 1024 * 1024
MAX_DECOMPRESSION_RATIO: Final[int] = 200

#: Interactive analysis ceilings.
MAX_UNIQUE_TIMESTAMPS_PER_RUN: Final[int] = 500
MAX_ANIMATION_FRAMES: Final[int] = 900
GRID_CELL_LIMITS: Final[tuple[int, int]] = (1_000, 250_000)

#: Machine-learning ceilings.
MAX_CANDIDATE_MODELS: Final[int] = 8
MAX_SEARCH_TRIALS_PER_MODEL: Final[int] = 40
MAX_SHAP_ROWS: Final[int] = 2_000

#: Hard ceiling for one export bundle. A run whose artifacts exceed this is
#: rejected with a structured error, never silently truncated.
MAX_EXPORT_BUNDLE_BYTES: Final[int] = 512 * 1024 * 1024

#: Analysis CRS default: UTM 44N, which covers the Chilika Lagoon basin.
DEFAULT_ANALYSIS_CRS: Final[str] = "EPSG:32644"

#: Numerical tolerances used by tests and by scientific comparisons.
GEOSPATIAL_TOLERANCES: Final[dict[str, float]] = {
    "coordinate_degrees": 1e-9,
    "projection_metres": 1e-3,
    "interpolation_value": 1e-9,
    "metric_absolute": 1e-9,
}

#: Artifact schema versions that this build can read.
SUPPORTED_SCHEMA_VERSIONS: Final[tuple[str, ...]] = ("1.0.0",)
