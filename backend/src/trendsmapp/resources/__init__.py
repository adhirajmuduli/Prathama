"""Versioned, read-only resource registries shipped with the package.

Resources are data, not code: they are YAML documents under this directory,
read through :mod:`importlib.resources` so they work from an installed wheel as
well as from a source checkout. Every document carries a ``schema_version``
that the loader validates before anything else, so a resource can never be
read with a reader written for a different version of it.
"""

from __future__ import annotations

import importlib.resources
from typing import Any, Final

import yaml

from trendsmapp.contracts.versions import parse_version
from trendsmapp.errors import ValidationError

__all__ = [
    "RESOURCES_PACKAGE",
    "SUPPORTED_RESOURCE_SCHEMA_VERSIONS",
    "load_yaml_resource",
    "read_resource_bytes",
    "read_resource_text",
]

#: The package that holds the resource documents.
RESOURCES_PACKAGE: Final[str] = "trendsmapp.resources"

#: Resource schema versions this build can read.
SUPPORTED_RESOURCE_SCHEMA_VERSIONS: Final[tuple[str, ...]] = ("1.0.0",)


def _resource_file(name: str) -> Any:
    """Return the resource handle for a plain file name, rejecting traversal."""
    if "/" in name or ".." in name or name.startswith("."):
        raise ValidationError(
            "A resource name must be a plain file name.",
            details={"name": name},
        )
    try:
        resource = importlib.resources.files(RESOURCES_PACKAGE).joinpath(name)
    except (FileNotFoundError, ModuleNotFoundError) as exc:
        raise ValidationError(
            f"The resource '{name}' is not shipped with this build.",
            details={"name": name},
        ) from exc
    if not resource.is_file():
        raise ValidationError(
            f"The resource '{name}' is not shipped with this build.",
            details={"name": name},
        )
    return resource


def read_resource_bytes(name: str) -> bytes:
    """Return the exact bytes of a resource, without any newline translation."""
    return _resource_file(name).read_bytes()


def read_resource_text(name: str) -> str:
    """Return the text of a resource document shipped in this package."""
    return _resource_file(name).read_text(encoding="utf-8")


def load_yaml_resource(name: str) -> dict[str, Any]:
    """Load and structurally validate a YAML resource document.

    The document must be a mapping with a ``schema_version`` string this build
    supports. Anything else is a validation error, never a silent default.
    """
    text = read_resource_text(name)
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValidationError(
            f"The resource '{name}' is not valid YAML.",
            details={"name": name},
        ) from exc
    if not isinstance(document, dict):
        raise ValidationError(
            f"The resource '{name}' must contain a mapping at the top level.",
            details={"name": name},
        )
    version = document.get("schema_version")
    if not isinstance(version, str):
        raise ValidationError(
            f"The resource '{name}' must declare a schema_version string.",
            details={"name": name},
        )
    if version not in SUPPORTED_RESOURCE_SCHEMA_VERSIONS:
        raise ValidationError(
            f"The resource '{name}' declares schema version '{version}', which this "
            "build does not support.",
            details={
                "name": name,
                "schema_version": version,
                "supported": list(SUPPORTED_RESOURCE_SCHEMA_VERSIONS),
            },
        )
    parse_version(version)
    return document
