"""Unit normalization: canonical names, alias resolution, dimension-checked conversion.

A unit is resolved in a fixed order, and each step is recorded:

1. a parameter unit alias, for spellings the unit registry cannot parse
   (``psu``, ``NTU``);
2. the unit registry itself, with the declared dimensionality check;
3. a casefolded retry, used only when the folded spelling also matches the
   parameter's dimension — pint is case-sensitive, and ``MG/L`` read as
   megagauss per litre is a different quantity, so the correction is
   reported, never silent.

Conversion to the parameter's canonical unit is dimension-checked by the
registry and records the factor that was applied.
"""

from __future__ import annotations

from dataclasses import dataclass

from trendsmapp.domain.units import UnitConversion, UnitRegistry, get_unit_registry
from trendsmapp.errors import ValidationError
from trendsmapp.normalization.parameters import Parameter, normalize_alias
from trendsmapp.normalization.values import ValueParseResult

__all__ = [
    "UnitNormalization",
    "ValueNormalization",
    "normalize_unit",
    "normalize_value",
]


@dataclass(frozen=True, slots=True)
class UnitNormalization:
    """The outcome of resolving one unit cell."""

    raw_unit: str
    unit_expression: str | None
    canonical_unit_name: str | None
    case_corrected: bool
    issue: str | None

    @property
    def resolved(self) -> bool:
        """Return whether the unit was resolved to a known expression."""
        return self.unit_expression is not None and self.issue is None


@dataclass(frozen=True, slots=True)
class ValueNormalization:
    """The canonical value, unit, and detection limit of one observation."""

    canonical_value: float | None
    canonical_unit: str | None
    detection_limit: float | None
    conversion: UnitConversion | None
    issues: tuple[str, ...]


def normalize_unit(
    unit_text: str,
    *,
    parameter: Parameter,
    unit_registry: UnitRegistry | None = None,
) -> UnitNormalization:
    """Resolve one unit cell against a parameter's registry entry.

    Candidates are tried in a fixed order and the first one whose
    dimensionality matches the parameter wins: a parameter unit alias for
    spellings pint cannot parse (``psu``), then the exact spelling, then a
    casefolded retry — pint is case-sensitive, and ``MG/L`` read as megagauss
    per litre is a different quantity, so a case correction is only accepted
    when the folded spelling also matches the parameter's dimension, and is
    always reported. A spelling that parses but does not match any candidate's
    dimension resolves with ``incompatible_unit``; one that parses nowhere
    resolves with ``unknown_unit``.
    """
    registry = unit_registry or get_unit_registry()
    raw = unit_text.strip()
    if not raw:
        return UnitNormalization(
            raw_unit=raw,
            unit_expression=None,
            canonical_unit_name=None,
            case_corrected=False,
            issue="missing_unit",
        )
    candidates: list[tuple[str, bool]] = []
    alias = normalize_alias(raw)
    if alias in parameter.unit_aliases:
        candidates.append((parameter.unit_aliases[alias], False))
    if registry.is_known(raw):
        candidates.append((raw, False))
    folded = raw.casefold()
    if folded != raw and registry.is_known(folded):
        candidates.append((folded, True))

    for expression, case_corrected in candidates:
        if registry.dimension_signature(expression) == parameter.dimension:
            return UnitNormalization(
                raw_unit=raw,
                unit_expression=expression,
                canonical_unit_name=registry.canonical_name(expression),
                case_corrected=case_corrected,
                issue=None,
            )
    if candidates:
        expression, case_corrected = candidates[0]
        return UnitNormalization(
            raw_unit=raw,
            unit_expression=expression,
            canonical_unit_name=registry.canonical_name(expression),
            case_corrected=case_corrected,
            issue="incompatible_unit",
        )
    return UnitNormalization(
        raw_unit=raw,
        unit_expression=None,
        canonical_unit_name=None,
        case_corrected=False,
        issue="unknown_unit",
    )


def normalize_value(
    value: ValueParseResult,
    unit: UnitNormalization,
    *,
    parameter: Parameter,
    unit_registry: UnitRegistry | None = None,
) -> ValueNormalization:
    """Convert a parsed value into the parameter's canonical unit.

    The dimension check happens before any arithmetic: a milligram-per-litre
    value can never become a metre-per-second value. A censored detection limit
    is converted with the same factor as the value would have been.
    """
    registry = unit_registry or get_unit_registry()
    issues: list[str] = []
    if unit.case_corrected:
        issues.append(f"unit case corrected from '{unit.raw_unit}' to '{unit.unit_expression}'")
    if not unit.resolved or unit.unit_expression is None:
        issues.append(unit.issue or "unknown_unit")
        return ValueNormalization(
            canonical_value=None,
            canonical_unit=None,
            detection_limit=None,
            conversion=None,
            issues=tuple(issues),
        )

    source_dimension = registry.dimension_signature(unit.unit_expression)
    if source_dimension != parameter.dimension:
        issues.append("incompatible_unit")
        return ValueNormalization(
            canonical_value=None,
            canonical_unit=None,
            detection_limit=None,
            conversion=None,
            issues=tuple(issues),
        )

    conversion: UnitConversion | None = None
    canonical_value: float | None = None
    detection_limit: float | None = None
    target = parameter.canonical_unit
    if value.value is not None:
        try:
            conversion = registry.convert(value.value, unit.unit_expression, target)
            canonical_value = conversion.value
        except ValidationError as exc:
            issues.append(f"conversion_failed: {exc.details}")
    if value.detection_limit is not None:
        try:
            limit_conversion = registry.convert(value.detection_limit, unit.unit_expression, target)
            detection_limit = limit_conversion.value
        except ValidationError as exc:
            issues.append(f"detection_limit_not_convertible: {exc.details}")
    return ValueNormalization(
        canonical_value=canonical_value,
        canonical_unit=target
        if (canonical_value is not None or detection_limit is not None)
        else None,
        detection_limit=detection_limit,
        conversion=conversion,
        issues=tuple(issues),
    )
