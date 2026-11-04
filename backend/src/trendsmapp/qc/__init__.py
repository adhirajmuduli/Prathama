"""Public QC exports.

Quality control turns observations into flagged observations. Nothing is ever
deleted here: every rule produces flags, and the exclusion policy — declared
per analysis, applied later — decides what an analysis uses.
"""

from __future__ import annotations

from trendsmapp.qc.completeness import CompletenessSummary, check_completeness
from trendsmapp.qc.coordinates import (
    BOUNDARY_GEOJSON,
    BOUNDARY_PROVENANCE,
    Boundary,
    check_coordinates,
    load_boundary,
)
from trendsmapp.qc.detection_limits import check_detection_limits
from trendsmapp.qc.duplicates import check_duplicate_locations
from trendsmapp.qc.models import (
    MAX_FLAG_SOURCE_ROWS,
    QcFlagEntry,
    QcParameterReport,
    QcReport,
)
from trendsmapp.qc.outliers import check_outliers
from trendsmapp.qc.pipeline import FAIL_FLAGS, QcPipeline, QcResult
from trendsmapp.qc.ranges import QcRanges, check_ranges, get_qc_ranges
from trendsmapp.qc.temporal import check_temporal

__all__ = [
    "BOUNDARY_GEOJSON",
    "BOUNDARY_PROVENANCE",
    "FAIL_FLAGS",
    "MAX_FLAG_SOURCE_ROWS",
    "Boundary",
    "CompletenessSummary",
    "QcFlagEntry",
    "QcParameterReport",
    "QcPipeline",
    "QcRanges",
    "QcReport",
    "QcResult",
    "check_completeness",
    "check_coordinates",
    "check_detection_limits",
    "check_duplicate_locations",
    "check_outliers",
    "check_ranges",
    "check_temporal",
    "get_qc_ranges",
    "load_boundary",
]
