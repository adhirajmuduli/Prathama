"""Command-line entry point.

The CLI exposes the operations that must behave exactly like the service:
reporting the version, exporting the OpenAPI snapshot used by contract CI,
and running the worker process.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from trendsmapp.logging_config import configure_logging
from trendsmapp.settings import get_settings
from trendsmapp.version import APPLICATION_VERSION

__all__ = ["app"]

app = typer.Typer(
    add_completion=False,
    help="Trendsmapp command line interface.",
    no_args_is_help=True,
)


@app.command()
def version() -> None:
    """Print the application version and the supported contract versions."""
    from trendsmapp.contracts.versions import (
        API_MAJOR_VERSION,
        ARTIFACT_SCHEMA_VERSION,
        RECIPE_SCHEMA_VERSION,
    )

    typer.echo(
        json.dumps(
            {
                "application_version": APPLICATION_VERSION,
                "api_major": API_MAJOR_VERSION,
                "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
                "recipe_schema_version": RECIPE_SCHEMA_VERSION,
            },
            indent=2,
        )
    )


@app.command("export-openapi")
def export_openapi(
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Write the snapshot to this path."),
    ] = None,
) -> None:
    """Export the OpenAPI snapshot of the API application."""
    from trendsmapp.api.app import create_app

    application = create_app()
    payload = json.dumps(application.openapi(), indent=2, sort_keys=True) + "\n"
    if output is None:
        typer.echo(payload)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(payload, encoding="utf-8")
    typer.echo(f"Wrote {output}")


@app.command()
def worker(
    poll_interval: Annotated[
        float | None,
        typer.Option("--poll-interval", help="Seconds between empty polls."),
    ] = None,
) -> None:
    """Run the worker process until it is stopped."""
    import asyncio

    from trendsmapp.services.ingestion import build_default_registry
    from trendsmapp.worker.main import run_worker

    settings = get_settings()
    if poll_interval is not None:
        settings = settings.model_copy(update={"worker_poll_interval_seconds": poll_interval})
    configure_logging(level=settings.log_level, json_output=settings.log_json)
    asyncio.run(run_worker(settings=settings, registry=build_default_registry()))
