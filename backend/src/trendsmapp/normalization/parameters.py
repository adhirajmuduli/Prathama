"""Canonical parameter registry: aliases, dimension, and unit checks.

The registry is loaded from the versioned resource ``parameters.v1.yaml`` and
validated against the unit registry at load time: a canonical unit that does
not parse, or whose dimensionality disagrees with the declared dimension, is a
load-time error, so a broken registry can never reach a dataset.

Alias resolution is total and deterministic: a label is matched against the
parameter id, the label, and the alias table, each after the same
normalization. A label that matches nothing resolves to ``None`` and is
reported as an unknown parameter downstream; it is never mapped by proximity.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Final

from trendsmapp import resources
from trendsmapp.domain.units import UnitRegistry, get_unit_registry
from trendsmapp.errors import ValidationError

__all__ = [
    "PARAMETER_RESOURCE",
    "Parameter",
    "ParameterRegistry",
    "ParameterResolution",
    "normalize_alias",
]

#: The resource document that holds the parameter registry.
PARAMETER_RESOURCE: Final[str] = "parameters.v1.yaml"

_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_]*$")


def normalize_alias(label: str) -> str:
    """Normalize a parameter label or unit alias for matching."""
    return re.sub(r"[^0-9a-z]+", "_", label.strip().casefold()).strip("_")


@dataclass(frozen=True, slots=True)
class Parameter:
    """One parameter of the canonical observation model."""

    id: str
    label: str
    display_name: str | None
    aliases: tuple[str, ...]
    canonical_unit: str
    dimension: str
    unit_aliases: dict[str, str]


@dataclass(frozen=True, slots=True)
class ParameterResolution:
    """The outcome of resolving one label against the registry."""

    parameter: Parameter | None
    label: str
    via: str

    @property
    def resolved(self) -> bool:
        """Return whether the label matched a registered parameter."""
        return self.parameter is not None


class ParameterRegistry:
    """The validated parameter registry loaded from the versioned resource."""

    def __init__(self, parameters: tuple[Parameter, ...], unit_registry: UnitRegistry) -> None:
        self._parameters = parameters
        self._by_id = {parameter.id: parameter for parameter in parameters}
        self._by_alias: dict[str, Parameter] = {}
        for parameter in parameters:
            self._by_alias[normalize_alias(parameter.id)] = parameter
            self._by_alias[normalize_alias(parameter.label)] = parameter
            for alias in parameter.aliases:
                self._by_alias[normalize_alias(alias)] = parameter
        self._unit_registry = unit_registry

    @property
    def parameters(self) -> tuple[Parameter, ...]:
        """Return every registered parameter in resource order."""
        return self._parameters

    def get(self, parameter_id: str) -> Parameter | None:
        """Return a parameter by id."""
        return self._by_id.get(parameter_id)

    def resolve(self, label: str) -> ParameterResolution:
        """Resolve a label to a parameter, recording how it matched."""
        key = normalize_alias(label)
        if not key:
            return ParameterResolution(parameter=None, label=label, via="none")
        if key in self._by_id:
            return ParameterResolution(parameter=self._by_id[key], label=label, via="id")
        parameter = self._by_alias.get(key)
        if parameter is None:
            return ParameterResolution(parameter=None, label=label, via="none")
        via = "label" if key == normalize_alias(parameter.label) else "alias"
        return ParameterResolution(parameter=parameter, label=label, via=via)

    @classmethod
    def load(cls) -> ParameterRegistry:
        """Load and validate the parameter registry from the shipped resource."""
        document = resources.load_yaml_resource(PARAMETER_RESOURCE)
        entries = document.get("parameters")
        if not isinstance(entries, list) or not entries:
            raise ValidationError(
                f"The resource '{PARAMETER_RESOURCE}' must declare a non-empty 'parameters' list.",
                details={"name": PARAMETER_RESOURCE},
            )
        unit_registry = get_unit_registry()
        parameters: list[Parameter] = []
        seen_ids: set[str] = set()
        seen_aliases: dict[str, str] = {}
        for entry in entries:
            parameter = _parse_parameter(entry, unit_registry)
            if parameter.id in seen_ids:
                raise ValidationError(
                    f"The parameter id '{parameter.id}' is declared twice in "
                    f"'{PARAMETER_RESOURCE}'.",
                    details={"parameter": parameter.id},
                )
            seen_ids.add(parameter.id)
            for alias in (parameter.label, *parameter.aliases):
                key = normalize_alias(alias)
                if key in seen_aliases and seen_aliases[key] != parameter.id:
                    raise ValidationError(
                        f"The alias '{alias}' is declared for both "
                        f"'{seen_aliases[key]}' and '{parameter.id}'.",
                        details={"alias": alias},
                    )
                seen_aliases[key] = parameter.id
            parameters.append(parameter)
        return cls(tuple(parameters), unit_registry)


def _parse_parameter(entry: Any, unit_registry: UnitRegistry) -> Parameter:
    """Validate one parameter entry against the registry of units."""
    if not isinstance(entry, dict):
        raise ValidationError(
            f"Every entry of '{PARAMETER_RESOURCE}' must be a mapping.",
            details={"name": PARAMETER_RESOURCE},
        )
    parameter_id = entry.get("id")
    label = entry.get("label")
    canonical_unit = entry.get("canonical_unit")
    dimension = entry.get("dimension")
    if not isinstance(parameter_id, str) or not _ID_PATTERN.fullmatch(parameter_id):
        raise ValidationError(
            f"A parameter id must match {_ID_PATTERN.pattern}.",
            details={"id": parameter_id},
        )
    if not isinstance(label, str) or not label.strip():
        raise ValidationError(
            f"The parameter '{parameter_id}' must declare a label.",
            details={"parameter": parameter_id},
        )
    if not isinstance(canonical_unit, str) or not canonical_unit.strip():
        raise ValidationError(
            f"The parameter '{parameter_id}' must declare a canonical unit.",
            details={"parameter": parameter_id},
        )
    if not isinstance(dimension, str) or not dimension.strip():
        raise ValidationError(
            f"The parameter '{parameter_id}' must declare a dimension.",
            details={"parameter": parameter_id},
        )
    aliases = entry.get("aliases", [])
    if not isinstance(aliases, list) or not all(isinstance(a, str) for a in aliases):
        raise ValidationError(
            f"The aliases of '{parameter_id}' must be a list of strings.",
            details={"parameter": parameter_id},
        )
    unit_aliases_raw = entry.get("unit_aliases", {})
    if not isinstance(unit_aliases_raw, dict):
        raise ValidationError(
            f"The unit_aliases of '{parameter_id}' must be a mapping.",
            details={"parameter": parameter_id},
        )
    unit_aliases: dict[str, str] = {}
    for alias, expression in unit_aliases_raw.items():
        if not isinstance(alias, str) or not isinstance(expression, str):
            raise ValidationError(
                f"The unit_aliases of '{parameter_id}' must map strings to strings.",
                details={"parameter": parameter_id},
            )
        unit_aliases[normalize_alias(alias)] = expression

    if not unit_registry.is_known(canonical_unit):
        raise ValidationError(
            f"The canonical unit '{canonical_unit}' of '{parameter_id}' is not a known unit.",
            details={"parameter": parameter_id, "unit": canonical_unit},
        )
    actual_dimension = unit_registry.dimension_signature(canonical_unit)
    if actual_dimension != dimension:
        raise ValidationError(
            f"The declared dimension '{dimension}' of '{parameter_id}' disagrees "
            f"with the unit registry, which reports '{actual_dimension}' for "
            f"'{canonical_unit}'.",
            details={
                "parameter": parameter_id,
                "declared": dimension,
                "actual": actual_dimension,
            },
        )
    for alias, expression in unit_aliases.items():
        if not unit_registry.is_known(expression):
            raise ValidationError(
                f"The unit alias '{alias}' of '{parameter_id}' maps to "
                f"'{expression}', which is not a known unit.",
                details={"parameter": parameter_id, "alias": alias},
            )
        alias_dimension = unit_registry.dimension_signature(expression)
        if alias_dimension != dimension:
            raise ValidationError(
                f"The unit alias '{alias}' of '{parameter_id}' has dimension "
                f"'{alias_dimension}', which disagrees with '{dimension}'.",
                details={"parameter": parameter_id, "alias": alias},
            )
    display_name = entry.get("display_name")
    return Parameter(
        id=parameter_id,
        label=label.strip(),
        display_name=display_name if isinstance(display_name, str) else None,
        aliases=tuple(alias.strip() for alias in aliases),
        canonical_unit=canonical_unit.strip(),
        dimension=dimension,
        unit_aliases=unit_aliases,
    )


@lru_cache(maxsize=1)
def get_parameter_registry() -> ParameterRegistry:
    """Return the process-wide parameter registry."""
    return ParameterRegistry.load()
