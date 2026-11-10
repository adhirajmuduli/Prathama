"""Pure, sequential artifact-schema migrations with no I/O.

A migration is a function from one stored document shape to the next. It must
be deterministic and side-effect free: it receives the document, returns a new
document, and never reads or writes anything. That property is what makes an
exported bundle reproducible years later.

Migrations are applied one version at a time. Applying a migration to a
document that is already at the target version is a no-op, which keeps
repeated runs idempotent. Downgrades are rejected: a newer document is never
silently rewritten as an older one.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from trendsmapp.contracts.versions import (
    ARTIFACT_SCHEMA_VERSION,
    compare_versions,
    parse_version,
)
from trendsmapp.errors import CompatibilityError

__all__ = [
    "ARTIFACT_SCHEMA_MIGRATIONS",
    "Migration",
    "MigrationRegistry",
    "migrate_artifact_document",
]

Document = dict[str, Any]
MigrationFunction = Callable[[Document], Document]

SCHEMA_VERSION_FIELD = "schema_version"


@dataclass(frozen=True, slots=True)
class Migration:
    """One sequential step between two schema versions."""

    from_version: str
    to_version: str
    migrate: MigrationFunction

    def apply(self, document: Document) -> Document:
        """Apply the migration to a document and return the migrated copy."""
        migrated = self.migrate(copy.deepcopy(document))
        migrated[SCHEMA_VERSION_FIELD] = self.to_version
        return migrated


class MigrationRegistry:
    """An ordered chain of migrations for one document family."""

    def __init__(self, name: str, *, baseline_version: str) -> None:
        self._name = name
        self._baseline_version = baseline_version
        self._migrations: list[Migration] = []

    @property
    def name(self) -> str:
        """Return the registry name, used in error messages."""
        return self._name

    @property
    def baseline_version(self) -> str:
        """Return the oldest version this registry understands."""
        return self._baseline_version

    @property
    def head_version(self) -> str:
        """Return the newest version this registry produces."""
        return self._migrations[-1].to_version if self._migrations else self._baseline_version

    @property
    def versions(self) -> tuple[str, ...]:
        """Return every version this registry understands, oldest first."""
        chain = [self._baseline_version]
        chain.extend(migration.to_version for migration in self._migrations)
        return tuple(chain)

    def register(self, migration: Migration) -> Migration:
        """Append a migration to the chain and return it."""
        expected_source = self.head_version
        if migration.from_version != expected_source:
            raise ValueError(
                f"Migration must start at '{expected_source}' "
                f"but declares '{migration.from_version}'."
            )
        if compare_versions(migration.to_version, migration.from_version) <= 0:
            raise ValueError("A migration must increase the schema version.")
        self._migrations.append(migration)
        return migration

    def path_to(self, target_version: str) -> tuple[Migration, ...]:
        """Return the migrations that lead from the baseline to ``target_version``."""
        if target_version == self._baseline_version:
            return ()
        chain: list[Migration] = []
        for migration in self._migrations:
            chain.append(migration)
            if migration.to_version == target_version:
                return tuple(chain)
        raise CompatibilityError(
            f"No {self._name} migration path reaches version '{target_version}'.",
            details={
                "registry": self._name,
                "requested_version": target_version,
                "known_versions": list(self.versions),
            },
        )

    def migrate(self, document: Mapping[str, Any], target_version: str) -> Document:
        """Migrate a stored document to ``target_version``."""
        raw_version = document.get(SCHEMA_VERSION_FIELD)
        if not isinstance(raw_version, str) or not raw_version:
            raise CompatibilityError(
                f"The {self._name} document does not declare a schema version.",
                details={"registry": self._name},
            )
        current_version = raw_version
        try:
            parse_version(current_version)
            parse_version(target_version)
        except CompatibilityError as exc:
            raise CompatibilityError(
                f"The {self._name} document or target version is malformed.",
                details=exc.details,
            ) from exc
        if compare_versions(current_version, target_version) > 0:
            raise CompatibilityError(
                f"Cannot downgrade a {self._name} document from "
                f"'{current_version}' to '{target_version}'.",
                details={
                    "registry": self._name,
                    "current_version": current_version,
                    "requested_version": target_version,
                },
            )
        if current_version == target_version:
            migrated = copy.deepcopy(dict(document))
            migrated[SCHEMA_VERSION_FIELD] = target_version
            return migrated
        if current_version not in self.versions:
            raise CompatibilityError(
                f"The {self._name} document version '{current_version}' is not supported.",
                details={
                    "registry": self._name,
                    "current_version": current_version,
                    "known_versions": list(self.versions),
                },
            )
        migrated = copy.deepcopy(dict(document))
        for migration in self._migrations:
            if migration.from_version != migrated[SCHEMA_VERSION_FIELD]:
                continue
            if compare_versions(migration.to_version, target_version) > 0:
                break
            migrated = migration.apply(migrated)
        if migrated[SCHEMA_VERSION_FIELD] != target_version:
            raise CompatibilityError(
                f"The {self._name} document could not be migrated to '{target_version}'.",
                details={
                    "registry": self._name,
                    "current_version": current_version,
                    "requested_version": target_version,
                },
            )
        return migrated


#: Registry for stored artifact documents such as manifests and result payloads.
ARTIFACT_SCHEMA_MIGRATIONS = MigrationRegistry("artifact", baseline_version=ARTIFACT_SCHEMA_VERSION)


def migrate_artifact_document(document: Mapping[str, Any], target_version: str) -> Document:
    """Migrate a stored artifact document to ``target_version``."""
    return ARTIFACT_SCHEMA_MIGRATIONS.migrate(document, target_version)
