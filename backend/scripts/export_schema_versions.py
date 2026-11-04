"""Export the supported contract versions used by the compatibility checks.

The file records every contract version this build speaks. It is generated
from the backend constants so that it can never drift from the code, and it is
checked in CI in the same way as the OpenAPI snapshot.

Usage::

    uv run python scripts/export_schema_versions.py --output ../contracts/schema-versions.json
    uv run python scripts/export_schema_versions.py --check ../contracts/schema-versions.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from trendsmapp.contracts.versions import (
    API_MAJOR_VERSION,
    APPLICATION_VERSION,
    ARTIFACT_SCHEMA_VERSION,
    RECIPE_SCHEMA_VERSION,
    SUPPORTED_API_MAJOR_VERSIONS,
    SUPPORTED_ARTIFACT_SCHEMA_VERSIONS,
    SUPPORTED_RECIPE_SCHEMA_VERSIONS,
)

DEFAULT_OUTPUT = Path("../contracts/schema-versions.json")


def render() -> str:
    """Return the deterministic version document of the current build."""
    document = {
        "application_version": APPLICATION_VERSION,
        "api_major_versions": list(SUPPORTED_API_MAJOR_VERSIONS),
        "current_api_major": API_MAJOR_VERSION,
        "artifact_schema_versions": list(SUPPORTED_ARTIFACT_SCHEMA_VERSIONS),
        "current_artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        "recipe_schema_versions": list(SUPPORTED_RECIPE_SCHEMA_VERSIONS),
        "current_recipe_schema_version": RECIPE_SCHEMA_VERSION,
        "manifest_schema_versions": list(SUPPORTED_ARTIFACT_SCHEMA_VERSIONS),
        "result_schema_versions": list(SUPPORTED_ARTIFACT_SCHEMA_VERSIONS),
    }
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def export(output: Path) -> Path:
    """Write the version document to ``output`` and return the path."""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(), encoding="utf-8")
    return output


def check(output: Path) -> int:
    """Return whether the committed version document matches the current build."""
    if not output.exists():
        print(f"export_schema_versions: {output} does not exist")
        return 1
    if output.read_text(encoding="utf-8") != render():
        print(
            f"export_schema_versions: {output} is out of date; "
            f"run 'uv run python scripts/export_schema_versions.py --output {output}'"
        )
        return 1
    print(f"export_schema_versions: {output} is current")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the exporter."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", nargs="?", default=None, help="the output path")
    parser.add_argument("--output", default=None, help="write the document to this path")
    parser.add_argument(
        "--check",
        default=None,
        help="compare the committed document with the current build",
    )
    arguments = parser.parse_args(argv)

    if arguments.check is not None:
        return check(Path(arguments.check))

    target = Path(arguments.output or arguments.target or DEFAULT_OUTPUT)
    written = export(target)
    print(written)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
