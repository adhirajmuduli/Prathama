"""Export the deterministic OpenAPI snapshot used by contract CI.

The application factory is imported without starting services: no database
connection is opened and no object store is contacted. The document is written
with sorted keys and a trailing newline so that the snapshot only changes when
the contract changes.

Usage::

    uv run python scripts/export_openapi.py --output ../contracts/openapi.v1.json
    uv run python scripts/export_openapi.py --check ../contracts/openapi.v1.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from trendsmapp.api.app import create_app

DEFAULT_OUTPUT = Path("../contracts/openapi.v1.json")


def render() -> str:
    """Return the deterministic OpenAPI document of the current application."""
    application = create_app()
    document = application.openapi()
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def export(output: Path) -> Path:
    """Write the OpenAPI document to ``output`` and return the path."""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(), encoding="utf-8")
    return output


def check(output: Path) -> int:
    """Return whether the committed snapshot matches the current application."""
    if not output.exists():
        print(f"export_openapi: {output} does not exist")
        return 1
    if output.read_text(encoding="utf-8") != render():
        print(
            f"export_openapi: {output} is out of date; "
            "run 'uv run python scripts/export_openapi.py --output "
            f"{output}'"
        )
        return 1
    print(f"export_openapi: {output} is current")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the exporter."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "target",
        nargs="?",
        default=None,
        help="the snapshot path; kept for positional invocations",
    )
    parser.add_argument("--output", default=None, help="write the snapshot to this path")
    parser.add_argument(
        "--check",
        default=None,
        help="compare the committed snapshot with the current application",
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
