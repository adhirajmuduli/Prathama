"""Public spatial method and result exports."""

from __future__ import annotations

from trendsmapp.spatial.base import (
    FittedInterpolator,
    FoldMetrics,
    Interpolator,
    MethodCapability,
    Prediction,
    SpatialMethodSpec,
    compute_metrics,
)
from trendsmapp.spatial.pipeline import (
    ArtifactSink,
    FrameMethodResult,
    FrameResult,
    SelectionDecision,
    SpatialRecipe,
    SpatialRunResult,
    run_spatial_analysis,
)
from trendsmapp.spatial.raster import RasterWriteResult, write_geotiff, write_masked_png
from trendsmapp.spatial.registry import (
    METHOD_CAPABILITIES,
    METHOD_REGISTRY,
    MethodEntry,
    capability_for,
    fit_method,
    validate_methods,
)
from trendsmapp.spatial.uncertainty import UncertaintyPayload, normalize_uncertainty
from trendsmapp.spatial.validation import (
    grouped_holdout,
    leave_one_station_out,
    spatial_block_holdout,
    spatial_block_ids,
    validate_method,
)

__all__ = [
    "METHOD_CAPABILITIES",
    "METHOD_REGISTRY",
    "ArtifactSink",
    "FittedInterpolator",
    "FoldMetrics",
    "FrameMethodResult",
    "FrameResult",
    "Interpolator",
    "MethodCapability",
    "MethodEntry",
    "Prediction",
    "RasterWriteResult",
    "SelectionDecision",
    "SpatialMethodSpec",
    "SpatialRecipe",
    "SpatialRunResult",
    "UncertaintyPayload",
    "capability_for",
    "compute_metrics",
    "fit_method",
    "grouped_holdout",
    "leave_one_station_out",
    "normalize_uncertainty",
    "run_spatial_analysis",
    "spatial_block_holdout",
    "spatial_block_ids",
    "validate_method",
    "validate_methods",
    "write_geotiff",
    "write_masked_png",
]
