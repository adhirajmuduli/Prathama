"""Public normalization exports.

Normalization turns the canonical long rows produced by the parser into
canonical observations. It never overwrites a raw value: every result keeps
the raw text beside the canonical value, and every failure is a coded issue
that quality control turns into a flag rather than a deletion.
"""

from __future__ import annotations

from trendsmapp.normalization.canonicalize import (
    CanonicalizationResult,
    NormalizedRow,
    RowIssue,
    SkippedRow,
    canonicalize_row,
    derive_station_key,
    observation_id_for,
)
from trendsmapp.normalization.coordinates import (
    CoordinateResult,
    normalize_projected,
    normalize_wgs84,
)
from trendsmapp.normalization.duplicates import (
    DuplicateGroup,
    DuplicateReport,
    find_duplicates,
)
from trendsmapp.normalization.parameters import (
    PARAMETER_RESOURCE,
    Parameter,
    ParameterRegistry,
    ParameterResolution,
    get_parameter_registry,
    normalize_alias,
)
from trendsmapp.normalization.pipeline import (
    CANONICAL_PARQUET_SCHEMA,
    MAX_RECORDED_SKIPPED_ROWS,
    MAX_SORT_IN_MEMORY_ROWS,
    NormalizationPipeline,
    NormalizationReport,
    NormalizationResult,
    ParquetArtifact,
    write_canonical_parquet,
)
from trendsmapp.normalization.timestamps import (
    apply_timezone_policy,
    parse_timestamp,
)
from trendsmapp.normalization.units import (
    UnitNormalization,
    ValueNormalization,
    normalize_unit,
    normalize_value,
)
from trendsmapp.normalization.values import ValueParseResult, parse_value

__all__ = [
    "CANONICAL_PARQUET_SCHEMA",
    "MAX_RECORDED_SKIPPED_ROWS",
    "MAX_SORT_IN_MEMORY_ROWS",
    "PARAMETER_RESOURCE",
    "CanonicalizationResult",
    "CoordinateResult",
    "DuplicateGroup",
    "DuplicateReport",
    "NormalizationPipeline",
    "NormalizationReport",
    "NormalizationResult",
    "NormalizedRow",
    "Parameter",
    "ParameterRegistry",
    "ParameterResolution",
    "ParquetArtifact",
    "RowIssue",
    "SkippedRow",
    "UnitNormalization",
    "ValueNormalization",
    "ValueParseResult",
    "apply_timezone_policy",
    "canonicalize_row",
    "derive_station_key",
    "find_duplicates",
    "get_parameter_registry",
    "normalize_alias",
    "normalize_projected",
    "normalize_unit",
    "normalize_value",
    "normalize_wgs84",
    "observation_id_for",
    "parse_timestamp",
    "parse_value",
    "write_canonical_parquet",
]
