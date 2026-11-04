"""Application version and build metadata access.

The version is the single source of truth for the application version embedded
in run manifests, API responses, and exported bundles. Build metadata is
supplied by the deployment pipeline through environment variables so that
importing the package never shells out or touches the filesystem.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Final

__all__ = ["APPLICATION_VERSION", "BuildMetadata", "build_metadata", "schema_version"]

APPLICATION_VERSION: Final[str] = "0.1.0"

_VERSION_ENVIRONMENT_VARIABLES: Final[tuple[tuple[str, str], ...]] = (
    ("commit", "TRENDSMAPP_BUILD_COMMIT"),
    ("built_at", "TRENDSMAPP_BUILD_TIMESTAMP"),
    ("builder", "TRENDSMAPP_BUILD_BUILDER"),
)


@dataclass(frozen=True, slots=True)
class BuildMetadata:
    """Immutable description of how the running artifact was produced."""

    commit: str | None = None
    built_at: str | None = None
    builder: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        """Return the metadata as a JSON-serializable mapping."""
        return {
            "commit": self.commit,
            "built_at": self.built_at,
            "builder": self.builder,
        }


def build_metadata() -> BuildMetadata:
    """Read build metadata from the process environment.

    Missing values are represented as ``None`` rather than invented, so a
    manifest never claims provenance that was not actually recorded.
    """
    values = {
        field: os.environ.get(variable, "").strip() or None
        for field, variable in _VERSION_ENVIRONMENT_VARIABLES
    }
    return BuildMetadata(
        commit=values["commit"],
        built_at=values["built_at"],
        builder=values["builder"],
    )


def schema_version() -> str:
    """Return the artifact schema version written into every result document."""
    from trendsmapp.contracts.versions import ARTIFACT_SCHEMA_VERSION

    return ARTIFACT_SCHEMA_VERSION
