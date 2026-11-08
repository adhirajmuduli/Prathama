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


@app.command()
def reproduce(
    bundle: Annotated[
        Path,
        typer.Argument(help="The export bundle ZIP to verify.", exists=True, dir_okay=False),
    ],
) -> None:
    """Verify an export bundle's checksums and print its manifest.

    Exits non-zero when any checksum, member, or manifest entry fails, so the
    command is usable as a CI reproduction gate.
    """
    from trendsmapp.reporting.verify import verify_bundle

    payload = bundle.read_bytes()
    report = verify_bundle(payload)
    typer.echo(
        json.dumps(
            {
                "bundle": str(bundle),
                "ok": report.ok,
                "checked_files": report.checked_files,
                "mismatches": list(report.mismatches),
                "missing": list(report.missing),
                "unexpected": list(report.unexpected),
                "run_id": report.manifest.get("run_id"),
                "recipe_hash": report.manifest.get("recipe_hash"),
                "dataset_sha256": report.manifest.get("dataset_sha256"),
                "application_version": report.manifest.get("application_version"),
                "generated_at": report.manifest.get("generated_at"),
            },
            indent=2,
        )
    )
    if not report.ok:
        raise typer.Exit(code=1)


@app.command()
def dev(
    host: Annotated[str, typer.Option("--host", help="The host to bind.")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", help="The port to bind.")] = 8000,
) -> None:
    """Run the API and the worker in one process, for local development and E2E.

    The worker runs in a daemon thread with its own event loop; the API serves
    in the main thread. Production deployments run them as separate processes.
    """
    import asyncio
    import threading

    import uvicorn

    from trendsmapp.services.ingestion import build_default_registry
    from trendsmapp.worker.main import run_worker

    settings = get_settings()
    configure_logging(level=settings.log_level, json_output=settings.log_json)

    # Local development applies the migrations itself; production runs the
    # separate migrate service before the API and worker start. The resolved
    # URL is exported so the Alembic environment migrates the same database
    # the application will use (os.getenv does not read .env files).
    import os

    os.environ["TRENDSMAPP_DATABASE_URL"] = settings.database_url
    from alembic.config import main as alembic_main

    typer.echo("Applying database migrations")
    alembic_main(argv=["-c", "alembic.ini", "upgrade", "head"])

    def _run_worker() -> None:
        asyncio.run(
            run_worker(settings=settings, registry=build_default_registry(), signal_handlers=False)
        )

    thread = threading.Thread(target=_run_worker, name="trendsmapp-worker", daemon=True)
    thread.start()
    typer.echo(f"Serving the API on http://{host}:{port} with the worker in-process")
    uvicorn.run(
        "trendsmapp.api.app:create_app",
        factory=True,
        host=host,
        port=port,
        log_level=settings.log_level.lower(),
    )
