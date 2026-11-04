"""Supported schema versions and compatibility predicates.

Three versions move independently:

* the application version (semantic version of Trendsmapp itself);
* the API version, whose major component is carried in the ``/api/v1`` path;
* the artifact schema version, embedded in every stored manifest and result.

Compatibility rules implemented here:

* an unknown API major version is rejected;
* an unknown artifact or recipe schema version is rejected;
* additive response fields within the same major version are safe for older
  clients, so a server may answer with a newer minor version;
* migrations move one version at a time and are never applied backwards.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from trendsmapp.errors import CompatibilityError
from trendsmapp.version import APPLICATION_VERSION

__all__ = [
    "API_MAJOR_VERSION",
    "APPLICATION_VERSION",
    "ARTIFACT_SCHEMA_VERSION",
    "RECIPE_SCHEMA_VERSION",
    "SUPPORTED_API_MAJOR_VERSIONS",
    "SUPPORTED_ARTIFACT_SCHEMA_VERSIONS",
    "SUPPORTED_RECIPE_SCHEMA_VERSIONS",
    "SemanticVersion",
    "compare_versions",
    "ensure_supported_api_major",
    "ensure_supported_artifact_schema",
    "ensure_supported_recipe_schema",
    "is_supported_api_major",
    "is_supported_artifact_schema",
    "is_supported_recipe_schema",
    "parse_version",
]

API_MAJOR_VERSION: Final[int] = 1
ARTIFACT_SCHEMA_VERSION: Final[str] = "1.0.0"
RECIPE_SCHEMA_VERSION: Final[str] = "1.0.0"

SUPPORTED_API_MAJOR_VERSIONS: Final[tuple[int, ...]] = (1,)
SUPPORTED_ARTIFACT_SCHEMA_VERSIONS: Final[tuple[str, ...]] = ("1.0.0",)
SUPPORTED_RECIPE_SCHEMA_VERSIONS: Final[tuple[str, ...]] = ("1.0.0",)

_VERSION_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


@dataclass(frozen=True, order=True, slots=True)
class SemanticVersion:
    """A comparable semantic version."""

    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


def parse_version(value: str) -> SemanticVersion:
    """Parse a strict ``major.minor.patch`` version string."""
    match = _VERSION_PATTERN.fullmatch(value.strip())
    if match is None:
        raise CompatibilityError(
            f"'{value}' is not a valid major.minor.patch version.",
            details={"value": value},
        )
    return SemanticVersion(
        major=int(match.group(1)),
        minor=int(match.group(2)),
        patch=int(match.group(3)),
    )


def compare_versions(left: str, right: str) -> int:
    """Return -1, 0, or 1 comparing two semantic versions."""
    parsed_left = parse_version(left)
    parsed_right = parse_version(right)
    if parsed_left < parsed_right:
        return -1
    if parsed_left > parsed_right:
        return 1
    return 0


def is_supported_api_major(major: int) -> bool:
    """Return whether an API major version is supported."""
    return major in SUPPORTED_API_MAJOR_VERSIONS


def is_supported_artifact_schema(version: str) -> bool:
    """Return whether an artifact schema version is supported."""
    return version in SUPPORTED_ARTIFACT_SCHEMA_VERSIONS


def is_supported_recipe_schema(version: str) -> bool:
    """Return whether a recipe schema version is supported."""
    return version in SUPPORTED_RECIPE_SCHEMA_VERSIONS


def ensure_supported_api_major(major: int) -> None:
    """Reject an unsupported API major version."""
    if not is_supported_api_major(major):
        raise CompatibilityError(
            f"API major version {major} is not supported by this deployment.",
            details={
                "requested_major": major,
                "supported_majors": list(SUPPORTED_API_MAJOR_VERSIONS),
            },
        )


def ensure_supported_artifact_schema(version: str) -> None:
    """Reject an unsupported artifact schema version."""
    if not is_supported_artifact_schema(version):
        raise CompatibilityError(
            f"Artifact schema version '{version}' is not supported by this deployment.",
            details={
                "requested_version": version,
                "supported_versions": list(SUPPORTED_ARTIFACT_SCHEMA_VERSIONS),
            },
        )


def ensure_supported_recipe_schema(version: str) -> None:
    """Reject an unsupported recipe schema version."""
    if not is_supported_recipe_schema(version):
        raise CompatibilityError(
            f"Recipe schema version '{version}' is not supported by this deployment.",
            details={
                "requested_version": version,
                "supported_versions": list(SUPPORTED_RECIPE_SCHEMA_VERSIONS),
            },
        )
