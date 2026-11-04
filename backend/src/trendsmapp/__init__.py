"""Trendsmapp backend package.

The public surface of this package is intentionally small: the application
version, the supported contract versions, and the stable names that other
packages import. Importing this package never opens a database connection,
reads environment variables, registers routes, or performs scientific work.
"""

from trendsmapp.contracts.versions import (
    API_MAJOR_VERSION,
    ARTIFACT_SCHEMA_VERSION,
    RECIPE_SCHEMA_VERSION,
    SUPPORTED_API_MAJOR_VERSIONS,
    SUPPORTED_ARTIFACT_SCHEMA_VERSIONS,
    SUPPORTED_RECIPE_SCHEMA_VERSIONS,
)
from trendsmapp.version import APPLICATION_VERSION

__all__ = [
    "API_MAJOR_VERSION",
    "APPLICATION_VERSION",
    "ARTIFACT_SCHEMA_VERSION",
    "RECIPE_SCHEMA_VERSION",
    "SUPPORTED_API_MAJOR_VERSIONS",
    "SUPPORTED_ARTIFACT_SCHEMA_VERSIONS",
    "SUPPORTED_RECIPE_SCHEMA_VERSIONS",
    "__version__",
]

__version__ = APPLICATION_VERSION
