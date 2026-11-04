"""Unit registry, canonical units, and dimension-checked conversion.

Conversions are dimension checked before they are performed: a value in
milligrams per litre can never be converted into metres per second, and the
attempt raises instead of producing a meaningless number. Every conversion
records the factor that was applied so the result stays auditable.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from pint import UnitRegistry as PintUnitRegistry
from pint.errors import DimensionalityError, UndefinedUnitError
from pint.facets.plain import PlainQuantity

from trendsmapp.errors import ValidationError

__all__ = ["UnitConversion", "UnitRegistry", "get_unit_registry"]


@dataclass(frozen=True, slots=True)
class UnitConversion:
    """The outcome of one unit conversion."""

    value: float
    from_unit: str
    to_unit: str
    factor: float
    dimension: str


class UnitRegistry:
    """A Pint-backed registry with strict parsing and explicit dimensionality."""

    def __init__(self) -> None:
        self._registry = PintUnitRegistry(autoconvert_offset_to_baseunit=True)

    def parse(self, text: str) -> PlainQuantity[Any]:
        """Parse a unit expression, raising a validation error when unknown."""
        cleaned = text.strip()
        if not cleaned:
            raise ValidationError("A unit expression is required.")
        try:
            return self._registry.parse_expression(cleaned)
        except UndefinedUnitError as exc:
            raise ValidationError(
                f"'{cleaned}' is not a recognized unit.",
                details={"unit": cleaned},
            ) from exc
        except (AttributeError, TypeError) as exc:
            raise ValidationError(
                f"'{cleaned}' is not a valid unit expression.",
                details={"unit": cleaned},
            ) from exc

    def is_known(self, text: str) -> bool:
        """Return whether a unit expression can be parsed."""
        try:
            self.parse(text)
        except ValidationError:
            return False
        return True

    def dimension_signature(self, text: str) -> str:
        """Return the dimensionality of a unit, for example ``[mass]``."""
        unit = self.parse(text)
        signature = str(unit.dimensionality)
        if signature == "dimensionless":
            return "dimensionless"
        return signature

    def canonical_name(self, text: str) -> str:
        """Return the registry's canonical name for a unit expression."""
        unit = self.parse(text)
        return str(unit.units)

    def to_base_units(self, value: float, unit: str) -> float:
        """Return the value expressed in the registry's base units."""
        parsed = self.parse(unit)
        return float(self._registry.convert(float(value), parsed, parsed.to_base_units()))

    def are_convertible(self, from_unit: str, to_unit: str) -> bool:
        """Return whether two units share a dimensionality."""
        try:
            self._registry.convert(1.0, self.parse(from_unit), self.parse(to_unit))
        except (DimensionalityError, UndefinedUnitError, AttributeError, TypeError):
            return False
        return True

    def convert(self, value: float, from_unit: str, to_unit: str) -> UnitConversion:
        """Convert ``value`` from one unit to another with a dimension check."""
        source = self.parse(from_unit)
        target = self.parse(to_unit)
        try:
            converted = self._registry.convert(float(value), source, target)
        except DimensionalityError as exc:
            raise ValidationError(
                f"Cannot convert '{from_unit}' to '{to_unit}': "
                "the units are not dimensionally compatible.",
                details={"from_unit": from_unit, "to_unit": to_unit},
            ) from exc
        except (UndefinedUnitError, AttributeError, TypeError) as exc:
            raise ValidationError(
                f"Cannot convert '{from_unit}' to '{to_unit}'.",
                details={"from_unit": from_unit, "to_unit": to_unit},
            ) from exc
        factor = self._conversion_factor(source, target)
        dimension = self.dimension_signature(to_unit)
        return UnitConversion(
            value=float(converted),
            from_unit=from_unit.strip(),
            to_unit=to_unit.strip(),
            factor=factor,
            dimension=dimension,
        )

    def _conversion_factor(self, source: PlainQuantity[Any], target: PlainQuantity[Any]) -> float:
        """Return the multiplicative factor between two compatible units."""
        try:
            factor = self._registry.convert(1.0, source, target)
        except (DimensionalityError, UndefinedUnitError, AttributeError, TypeError):
            return 1.0
        if factor == 0:
            return 1.0
        return float(factor)


@lru_cache(maxsize=1)
def get_unit_registry() -> UnitRegistry:
    """Return the process-wide unit registry."""
    return UnitRegistry()
