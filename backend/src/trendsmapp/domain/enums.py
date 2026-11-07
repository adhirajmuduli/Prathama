"""Controlled scientific and workflow enumerations.

Every enumeration that changes scientific meaning lives here so that the
domain, the contracts, the persistence layer, and the API all speak about the
same closed set of values.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "SETTING_SPLIT_FAMILIES",
    "CensoringPolicy",
    "ColumnRole",
    "DateOrder",
    "DuplicatePolicy",
    "ExclusionPolicy",
    "ExplanationMethod",
    "ExtrapolationPolicy",
    "FileFormat",
    "FrameStatus",
    "JobStatus",
    "JobType",
    "LayoutKind",
    "ModelFamily",
    "PredictionSetting",
    "QcFlagCode",
    "QcStatus",
    "SpatialMethod",
    "SplitStrategy",
    "TemporalInterpolation",
    "TimezonePolicy",
    "UncertaintyMethod",
    "ValueQualifier",
]


class ColumnRole(StrEnum):
    """The canonical role a source column plays in the observation model.

    A role is a claim the analyst confirms, never a guess the parser makes.
    ``IGNORED`` marks a column that is read for the parse report but excluded
    from the canonical dataset.
    """

    STATION = "station"
    LATITUDE = "latitude"
    LONGITUDE = "longitude"
    EASTING = "easting"
    NORTHING = "northing"
    TIMESTAMP = "timestamp"
    PARAMETER = "parameter"
    VALUE = "value"
    UNIT = "unit"
    QUALIFIER = "qualifier"
    DEPTH = "depth"
    SECTOR = "sector"
    IGNORED = "ignored"


class DateOrder(StrEnum):
    """The declared order of day, month, and year in a numeric date.

    ISO 8601 dates are unambiguous and unaffected. A numeric date such as
    ``03/04/2024`` means different days under different conventions, so the
    convention is declared in the column mapping instead of being guessed.
    """

    DAY_FIRST = "day_first"
    MONTH_FIRST = "month_first"
    YEAR_FIRST = "year_first"


class TimezonePolicy(StrEnum):
    """How a timestamp without an explicit offset is interpreted."""

    ASSUME_UTC = "assume_utc"
    REQUIRE_OFFSET = "require_offset"
    NAMED = "named"


class ValueQualifier(StrEnum):
    """How a raw measurement value relates to the reported canonical value."""

    MEASURED = "measured"
    BELOW_DETECTION_LIMIT = "below_detection_limit"
    ABOVE_DETECTION_LIMIT = "above_detection_limit"
    NOT_DETECTED = "not_detected"
    ESTIMATED = "estimated"
    CENSORED = "censored"


class QcStatus(StrEnum):
    """The aggregate quality-control state of an observation."""

    NOT_EVALUATED = "not_evaluated"
    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"


class QcFlagCode(StrEnum):
    """Individual quality-control findings.

    A flag records a finding; it never deletes the observation. Exclusion is a
    separate, explicit decision recorded on the observation itself.
    """

    INVALID_COORDINATE = "invalid_coordinate"
    OUTSIDE_BOUNDARY = "outside_boundary"
    COORDINATE_OUT_OF_RANGE = "coordinate_out_of_range"
    NON_FINITE_VALUE = "non_finite_value"
    INVALID_VALUE = "invalid_value"
    VALUE_BELOW_PHYSICAL_RANGE = "value_below_physical_range"
    VALUE_ABOVE_PHYSICAL_RANGE = "value_above_physical_range"
    MISSING_VALUE = "missing_value"
    MISSING_TIMESTAMP = "missing_timestamp"
    AMBIGUOUS_TIMESTAMP = "ambiguous_timestamp"
    IMPOSSIBLE_TIMESTAMP = "impossible_timestamp"
    DUPLICATE_OBSERVATION = "duplicate_observation"
    DUPLICATE_STATION = "duplicate_station"
    STATION_DRIFT = "station_drift"
    DETECTION_LIMIT_MISMATCH = "detection_limit_mismatch"
    DETECTION_LIMIT_INCONSISTENT = "detection_limit_inconsistent"
    UNKNOWN_PARAMETER = "unknown_parameter"
    UNKNOWN_UNIT = "unknown_unit"
    INCOMPATIBLE_UNIT = "incompatible_unit"
    REPEATED_VISIT = "repeated_visit"
    SAMPLING_GAP = "sampling_gap"
    ABRUPT_JUMP = "abrupt_jump"
    OUTLIER_ROBUST = "outlier_robust"
    MISSING_SECTOR = "missing_sector"
    AMBIGUOUS_SECTOR = "ambiguous_sector"


class DuplicatePolicy(StrEnum):
    """How exact and semantic duplicates are resolved."""

    FLAG_ALL = "flag_all"
    KEEP_FIRST = "keep_first"
    KEEP_LAST = "keep_last"
    KEEP_MOST_COMPLETE = "keep_most_complete"
    ERROR = "error"


class ExclusionPolicy(StrEnum):
    """Which flagged observations are excluded from analysis."""

    NONE = "none"
    EXCLUDE_INVALID = "exclude_invalid"
    EXCLUDE_FLAGGED = "exclude_flagged"


class CensoringPolicy(StrEnum):
    """How censored values below a detection limit enter calculations."""

    KEEP_AS_LIMIT = "keep_as_limit"
    SUBSTITUTE_HALF = "substitute_half"
    SUBSTITUTE_ZERO = "substitute_zero"
    EXCLUDE = "exclude"


class ExtrapolationPolicy(StrEnum):
    """Whether temporal interpolation may continue beyond observed periods."""

    NONE = "none"
    LINEAR = "linear"
    PCHIP = "pchip"


class SpatialMethod(StrEnum):
    """The approved spatial interpolation methods."""

    IDW = "idw"
    RBF = "rbf"
    KRIGING = "kriging"
    GAUSSIAN_PROCESS = "gaussian_process"


class TemporalInterpolation(StrEnum):
    """The approved temporal interpolation methods."""

    LINEAR = "linear"
    PCHIP = "pchip"


class FrameStatus(StrEnum):
    """Whether an animation frame is observed, interpolated, or unavailable."""

    OBSERVED = "observed"
    INTERPOLATED = "interpolated"
    UNAVAILABLE = "unavailable"


class LayoutKind(StrEnum):
    """The detected table layout."""

    LONG = "long"
    WIDE = "wide"
    UNKNOWN = "unknown"


class FileFormat(StrEnum):
    """The supported input file formats."""

    CSV = "csv"
    TSV = "tsv"
    XLSX = "xlsx"
    PARQUET = "parquet"


class JobType(StrEnum):
    """The job families executed by the worker."""

    INGEST = "ingest"
    ANALYZE = "analyze"
    TRAIN = "train"
    ANIMATE = "animate"
    EXPORT = "export"


class JobStatus(StrEnum):
    """The lifecycle states of a durable job."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ModelFamily(StrEnum):
    """The approved model families, each backed by a registry adapter.

    The baselines are implemented in :mod:`trendsmapp.ml.baselines`; the rest are
    adapters over documented estimators from scikit-learn or XGBoost.
    """

    MEAN_BASELINE = "mean_baseline"
    STATION_CLIMATOLOGY = "station_climatology"
    SEASONAL_CLIMATOLOGY = "seasonal_climatology"
    ELASTIC_NET = "elastic_net"
    RANDOM_FOREST = "random_forest"
    EXTRA_TREES = "extra_trees"
    HIST_GRADIENT_BOOSTING = "hist_gradient_boosting"
    XGBOOST = "xgboost"


class PredictionSetting(StrEnum):
    """What the model is asked to predict; each has an allowed split family."""

    KNOWN_STATION_TEMPORAL = "known_station_temporal"
    UNSEEN_STATION_SPATIAL = "unseen_station_spatial"
    FUTURE_PERIOD = "future_period"
    MISSING_RECONSTRUCTION = "missing_reconstruction"


class SplitStrategy(StrEnum):
    """How outer evaluation folds are generated."""

    STATION_GROUP = "station_group"
    SPATIAL_BLOCK = "spatial_block"
    LEAVE_YEAR_OUT = "leave_year_out"
    ROLLING_ORIGIN = "rolling_origin"
    SECTOR = "sector"
    COMBINED = "combined"
    RANDOM_ROW = "random_row"


#: Split families allowed per prediction setting. Random row splitting is never
#: allowed for claims that need held-out stations or future periods.
SETTING_SPLIT_FAMILIES: dict[PredictionSetting, frozenset[SplitStrategy]] = {
    PredictionSetting.KNOWN_STATION_TEMPORAL: frozenset(
        {
            SplitStrategy.STATION_GROUP,
            SplitStrategy.LEAVE_YEAR_OUT,
            SplitStrategy.ROLLING_ORIGIN,
            SplitStrategy.SECTOR,
            SplitStrategy.COMBINED,
        }
    ),
    PredictionSetting.UNSEEN_STATION_SPATIAL: frozenset(
        {
            SplitStrategy.STATION_GROUP,
            SplitStrategy.SPATIAL_BLOCK,
            SplitStrategy.SECTOR,
            SplitStrategy.COMBINED,
        }
    ),
    PredictionSetting.FUTURE_PERIOD: frozenset(
        {
            SplitStrategy.LEAVE_YEAR_OUT,
            SplitStrategy.ROLLING_ORIGIN,
            SplitStrategy.COMBINED,
        }
    ),
    PredictionSetting.MISSING_RECONSTRUCTION: frozenset(
        {
            SplitStrategy.STATION_GROUP,
            SplitStrategy.SPATIAL_BLOCK,
            SplitStrategy.LEAVE_YEAR_OUT,
            SplitStrategy.ROLLING_ORIGIN,
            SplitStrategy.SECTOR,
            SplitStrategy.COMBINED,
            SplitStrategy.RANDOM_ROW,
        }
    ),
}


class UncertaintyMethod(StrEnum):
    """How prediction intervals are produced."""

    BOOTSTRAP_ENSEMBLE = "bootstrap_ensemble"
    QUANTILE = "quantile"


class ExplanationMethod(StrEnum):
    """The explanation methods a task may request."""

    PERMUTATION = "permutation"
    SHAP_TREE = "shap_tree"
    PARTIAL_DEPENDENCE = "partial_dependence"
