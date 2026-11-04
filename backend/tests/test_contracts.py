"""Tests for schema versions, compatibility negotiation, and migrations."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from trendsmapp.contracts.common import ArtifactRef, PageMeta, Warning
from trendsmapp.contracts.compatibility import (
    API_VERSION_HEADER,
    RECIPE_SCHEMA_VERSION_HEADER,
    ResponseCompatibility,
    negotiate_api_major,
    negotiate_recipe_schema_version,
)
from trendsmapp.contracts.migrations import (
    ARTIFACT_SCHEMA_MIGRATIONS,
    Migration,
    MigrationRegistry,
    migrate_artifact_document,
)
from trendsmapp.contracts.versions import (
    API_MAJOR_VERSION,
    ARTIFACT_SCHEMA_VERSION,
    RECIPE_SCHEMA_VERSION,
    compare_versions,
    ensure_supported_api_major,
    ensure_supported_artifact_schema,
    ensure_supported_recipe_schema,
    parse_version,
)
from trendsmapp.errors import CompatibilityError


def test_parse_version_rejects_malformed_versions() -> None:
    assert parse_version("1.2.3").major == 1
    with pytest.raises(CompatibilityError):
        parse_version("1.2")
    with pytest.raises(CompatibilityError):
        parse_version("v1.2.3")


def test_compare_versions_orders_versions() -> None:
    assert compare_versions("1.0.0", "1.0.1") == -1
    assert compare_versions("1.1.0", "1.0.9") == 1
    assert compare_versions("1.0.0", "1.0.0") == 0


def test_unknown_api_major_version_is_rejected() -> None:
    ensure_supported_api_major(API_MAJOR_VERSION)
    with pytest.raises(CompatibilityError):
        ensure_supported_api_major(2)


def test_unknown_schema_versions_are_rejected() -> None:
    ensure_supported_artifact_schema(ARTIFACT_SCHEMA_VERSION)
    ensure_supported_recipe_schema(RECIPE_SCHEMA_VERSION)
    with pytest.raises(CompatibilityError):
        ensure_supported_artifact_schema("9.9.9")
    with pytest.raises(CompatibilityError):
        ensure_supported_recipe_schema("9.9.9")


def test_negotiate_api_major_defaults_to_current() -> None:
    assert negotiate_api_major(None, None) == API_MAJOR_VERSION
    assert negotiate_api_major({API_VERSION_HEADER: "1"}, None) == 1
    with pytest.raises(CompatibilityError):
        negotiate_api_major({API_VERSION_HEADER: "2"}, None)
    with pytest.raises(CompatibilityError):
        negotiate_api_major({API_VERSION_HEADER: "not-a-number"}, None)


def test_negotiate_recipe_schema_prefers_the_body_field() -> None:
    assert negotiate_recipe_schema_version(None, None) == RECIPE_SCHEMA_VERSION
    assert (
        negotiate_recipe_schema_version({RECIPE_SCHEMA_VERSION_HEADER: "1.0.0"}, None)
        == RECIPE_SCHEMA_VERSION
    )
    with pytest.raises(CompatibilityError):
        negotiate_recipe_schema_version(None, "2.0.0")


def _rename_unit(document: dict[str, Any]) -> dict[str, Any]:
    document["unit"] = document.pop("unit_name")
    return document


def test_migration_registry_applies_steps_sequentially() -> None:
    registry = MigrationRegistry("test", baseline_version="1.0.0")
    registry.register(Migration("1.0.0", "1.1.0", _rename_unit))
    registry.register(
        Migration(
            "1.1.0",
            "1.2.0",
            lambda document: {**document, "normalized": True},
        )
    )
    migrated = registry.migrate({"schema_version": "1.0.0", "unit_name": "mg/L"}, "1.2.0")
    assert migrated == {"schema_version": "1.2.0", "unit": "mg/L", "normalized": True}
    assert registry.head_version == "1.2.0"


def test_migration_is_idempotent_at_the_target_version() -> None:
    registry = MigrationRegistry("test", baseline_version="1.0.0")
    registry.register(Migration("1.0.0", "1.1.0", _rename_unit))
    document = {"schema_version": "1.1.0", "unit": "mg/L"}
    assert registry.migrate(document, "1.1.0") == document


def test_migration_rejects_downgrades_and_unknown_versions() -> None:
    registry = MigrationRegistry("test", baseline_version="1.0.0")
    with pytest.raises(CompatibilityError):
        registry.migrate({"schema_version": "1.0.0"}, "0.9.0")
    with pytest.raises(CompatibilityError):
        registry.migrate({"schema_version": "7.0.0"}, "1.0.0")
    with pytest.raises(CompatibilityError):
        registry.migrate({"no_version": True}, "1.0.0")


def test_migration_registry_rejects_out_of_order_registration() -> None:
    registry = MigrationRegistry("test", baseline_version="1.0.0")
    with pytest.raises(ValueError, match="must start at"):
        registry.register(Migration("2.0.0", "2.1.0", _rename_unit))


def test_production_artifact_registry_understands_the_current_version() -> None:
    document = {"schema_version": ARTIFACT_SCHEMA_VERSION, "run_id": "run_x"}
    assert migrate_artifact_document(document, ARTIFACT_SCHEMA_VERSION) == document
    assert ARTIFACT_SCHEMA_MIGRATIONS.baseline_version == ARTIFACT_SCHEMA_VERSION


def test_migration_registry_rejects_a_migration_that_does_not_increase_the_version() -> None:
    registry = MigrationRegistry("test", baseline_version="1.0.0")
    with pytest.raises(ValueError, match="increase the schema version"):
        registry.register(Migration("1.0.0", "1.0.0", _rename_unit))


def test_migration_registry_reports_its_name() -> None:
    assert MigrationRegistry("artifact", baseline_version="1.0.0").name == "artifact"


def test_migration_skips_steps_that_do_not_apply_and_stops_at_the_target() -> None:
    registry = MigrationRegistry("test", baseline_version="1.0.0")
    registry.register(Migration("1.0.0", "1.1.0", _rename_unit))
    registry.register(
        Migration(
            "1.1.0",
            "1.2.0",
            lambda document: {**document, "normalized": True},
        )
    )
    partial = registry.migrate({"schema_version": "1.0.0", "unit_name": "mg/L"}, "1.1.0")
    assert partial["schema_version"] == "1.1.0"
    assert "normalized" not in partial

    already_migrated = registry.migrate({"schema_version": "1.1.0", "unit": "mg/L"}, "1.2.0")
    assert already_migrated["normalized"] is True


def test_migration_to_an_unreachable_target_is_rejected() -> None:
    registry = MigrationRegistry("test", baseline_version="1.0.0")
    registry.register(Migration("1.0.0", "1.1.0", _rename_unit))
    with pytest.raises(CompatibilityError):
        registry.migrate({"schema_version": "1.0.0", "unit_name": "mg/L"}, "1.2.0")


def test_migration_rejects_a_malformed_target_version() -> None:
    registry = MigrationRegistry("test", baseline_version="1.0.0")
    with pytest.raises(CompatibilityError):
        registry.migrate({"schema_version": "1.0.0"}, "not-a-version")


def test_semantic_versions_render_themselves() -> None:
    assert str(parse_version("2.3.4")) == "2.3.4"


def test_shared_contract_primitives_expose_pagination_and_timestamps() -> None:
    artifact = ArtifactRef(
        artifact_id="art_" + "a" * 32,
        kind="normalized_dataset",
        sha256="b" * 64,
        size_bytes=1024,
        content_type="application/vnd.apache.parquet",
        created_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
    )
    assert artifact.created_at_iso == "2026-01-02T03:04:05Z"
    assert PageMeta(offset=0, limit=10, total=25).has_more is True
    assert PageMeta(offset=20, limit=10, total=25).has_more is False
    assert Warning(code="qc_warning", message="Outliers flagged.").severity == "warning"
    assert ResponseCompatibility().api_major == API_MAJOR_VERSION
