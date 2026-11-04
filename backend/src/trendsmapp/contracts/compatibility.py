"""Request-version negotiation and response compatibility metadata.

Clients may declare the contract version they speak either in a request header
or in a request body field. The negotiation rules are deliberately strict:

* an unknown API major version is rejected instead of being served with the
  closest match;
* an unknown recipe schema version is rejected;
* a missing version means "the current version";
* responses carry the versions they were produced with so that a client can
  record what it actually received.
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict

from trendsmapp.contracts.versions import (
    API_MAJOR_VERSION,
    APPLICATION_VERSION,
    ARTIFACT_SCHEMA_VERSION,
    RECIPE_SCHEMA_VERSION,
    ensure_supported_api_major,
    ensure_supported_recipe_schema,
)
from trendsmapp.errors import CompatibilityError

__all__ = [
    "API_VERSION_HEADER",
    "RECIPE_SCHEMA_VERSION_HEADER",
    "ResponseCompatibility",
    "negotiate_api_major",
    "negotiate_recipe_schema_version",
]

API_VERSION_HEADER = "X-Trendsmapp-Api-Version"
RECIPE_SCHEMA_VERSION_HEADER = "X-Trendsmapp-Recipe-Schema-Version"


class ResponseCompatibility(BaseModel):
    """The versions a response was produced with."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    api_major: int = API_MAJOR_VERSION
    artifact_schema_version: str = ARTIFACT_SCHEMA_VERSION
    recipe_schema_version: str = RECIPE_SCHEMA_VERSION
    application_version: str = APPLICATION_VERSION


def negotiate_api_major(
    headers: Mapping[str, str] | None = None,
    requested_major: int | None = None,
) -> int:
    """Resolve the API major version for a request.

    The explicit argument wins over the header. An unsupported major version
    raises :class:`CompatibilityError`.
    """
    candidate = requested_major
    if candidate is None and headers is not None:
        raw = headers.get(API_VERSION_HEADER) or headers.get(API_VERSION_HEADER.lower())
        if raw is not None and raw.strip():
            try:
                candidate = int(raw.strip())
            except ValueError as exc:
                raise CompatibilityError(
                    f"'{raw}' is not a valid API major version.",
                    details={"header": API_VERSION_HEADER, "value": raw},
                ) from exc
    if candidate is None:
        return API_MAJOR_VERSION
    ensure_supported_api_major(candidate)
    return candidate


def negotiate_recipe_schema_version(
    headers: Mapping[str, str] | None = None,
    body_version: str | None = None,
) -> str:
    """Resolve the recipe schema version for a request.

    The body field wins over the header. An unsupported version raises
    :class:`CompatibilityError`.
    """
    candidate = body_version
    if candidate is None and headers is not None:
        raw = headers.get(RECIPE_SCHEMA_VERSION_HEADER) or headers.get(
            RECIPE_SCHEMA_VERSION_HEADER.lower()
        )
        if raw is not None and raw.strip():
            candidate = raw.strip()
    if candidate is None:
        return RECIPE_SCHEMA_VERSION
    ensure_supported_recipe_schema(candidate)
    return candidate
