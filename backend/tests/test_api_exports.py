"""End-to-end tests for the exports API and the export worker job."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import httpx

from trendsmapp.domain.enums import JobType
from trendsmapp.hashing import sha256_bytes
from trendsmapp.reporting import verify_bundle
from trendsmapp.services.ingestion import build_default_registry
from trendsmapp.worker.main import Worker


async def _upload_and_ingest(client: httpx.AsyncClient, testdata_path: Path) -> str:
    """Upload the multi-station long fixture, create a dataset, return the version id."""
    payload = testdata_path("long_multi_station.csv").read_bytes()
    create = await client.post(
        "/api/v1/uploads",
        json={
            "filename": "long_multi_station.csv",
            "content_type": "text/csv",
            "size_bytes": len(payload),
            "sha256": sha256_bytes(payload),
        },
    )
    assert create.status_code == 201
    upload_id = create.json()["upload_id"]
    put = await client.put(f"/api/v1/uploads/{upload_id}/parts/1", content=payload)
    assert put.status_code == 200
    complete = await client.post(f"/api/v1/uploads/{upload_id}/complete")
    assert complete.status_code == 200
    probe = await client.post(f"/api/v1/uploads/{upload_id}/probe")
    assert probe.status_code == 200
    created = await client.post(
        "/api/v1/datasets",
        json={
            "upload_id": upload_id,
            "name": "export pilot",
            "mapping": probe.json()["proposed_mapping"],
        },
    )
    assert created.status_code == 202
    return created.json()["version_id"]


def _recipe(version_id: str) -> dict:
    return {
        "schema_version": "1.0.0",
        "dataset_version_id": version_id,
        "seed": 7,
        "spatial": {
            "methods": [{"method": "idw", "params": {"power": 2.0}}],
            "grid_resolution_m": 5_000.0,
            "max_grid_cells": 250_000,
            "analysis_crs": "EPSG:32644",
            "validation": "leave_one_station_out",
            "selection_rule": "best_rmse",
            "permitted_qc_statuses": ["pass", "warning"],
        },
        "temporal": {
            "resolution": "day",
            "interpolation": "linear",
            "max_gap_days": 30,
            "frame_count": 0,
            "compute_trends": True,
            "compute_change_points": False,
        },
    }


async def _sealed_version(
    client: httpx.AsyncClient, settings, engine, store, testdata_path: Path
) -> str:
    version_id = await _upload_and_ingest(client, testdata_path)
    worker = Worker(
        settings=settings, engine=engine, object_store=store, registry=build_default_registry()
    )
    for _ in range(3):
        await worker.run_once()
    version = await client.get(f"/api/v1/dataset-versions/{version_id}")
    assert version.json()["sealed"] is True
    return version_id


async def _succeeded_run(
    client: httpx.AsyncClient, settings, engine, store, testdata_path: Path
) -> str:
    version_id = await _sealed_version(client, settings, engine, store, testdata_path)
    created = await client.post("/api/v1/analyses", json=_recipe(version_id))
    assert created.status_code == 202
    run_id = created.json()["run_id"]
    worker = Worker(
        settings=settings, engine=engine, object_store=store, registry=build_default_registry()
    )
    for _ in range(2):
        await worker.run_once()
    run = await client.get(f"/api/v1/analyses/{run_id}")
    assert run.json()["status"] == "succeeded"
    return run_id


def test_default_registry_registers_export_handler() -> None:
    assert build_default_registry().supports(JobType.EXPORT)


async def test_export_end_to_end(
    client: httpx.AsyncClient, settings, engine, store, testdata_path: Path
) -> None:
    run_id = await _succeeded_run(client, settings, engine, store, testdata_path)

    created = await client.post("/api/v1/exports", json={"run_id": run_id})
    assert created.status_code == 202
    body = created.json()
    export_id = body["export_id"]
    assert export_id.startswith("exp_")
    assert body["job_id"].startswith("job_")

    # Reposting the same run returns the original export (idempotent).
    again = await client.post("/api/v1/exports", json={"run_id": run_id})
    assert again.status_code == 202
    assert again.json()["export_id"] == export_id

    worker = Worker(
        settings=settings, engine=engine, object_store=store, registry=build_default_registry()
    )
    for _ in range(2):
        await worker.run_once()  # the export job

    found = await client.get(f"/api/v1/exports/{export_id}")
    assert found.status_code == 200
    export = found.json()
    assert export["run_id"] == run_id
    assert export["status"] == "succeeded"
    assert export["artifact"]["kind"] == "export_bundle"
    assert export["manifest"]["run_id"] == run_id
    assert export["manifest"]["recipe_hash"]
    assert export["manifest"]["dataset_sha256"]
    assert export["manifest"]["artifacts"]

    download = await client.get(f"/api/v1/exports/{export_id}/download")
    assert download.status_code == 200
    assert download.headers["x-artifact-sha256"] == export["artifact"]["sha256"]
    assert download.headers["content-type"].startswith("application/zip")
    bundle = download.content
    assert bundle[:2] == b"PK"

    report = verify_bundle(bundle)
    assert report.ok
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        names = set(archive.namelist())
    assert {"manifest.json", "checksums.sha256", "methods.json", "README.md"} <= names
    assert "tables/analysis-frames.csv" in names
    assert any(name.startswith("artifacts/") for name in names)
    assert any(name.startswith("dataset/") for name in names)


async def test_export_rejects_bad_requests(
    client: httpx.AsyncClient, settings, engine, store, testdata_path: Path
) -> None:
    # Unknown run: 404.
    response = await client.post("/api/v1/exports", json={"run_id": "run_" + "0" * 32})
    assert response.status_code == 404

    # Run that has not succeeded yet: 409 before any job is enqueued.
    version_id = await _sealed_version(client, settings, engine, store, testdata_path)
    created = await client.post("/api/v1/analyses", json=_recipe(version_id))
    assert created.status_code == 202
    run_id = created.json()["run_id"]
    response = await client.post("/api/v1/exports", json={"run_id": run_id})
    assert response.status_code == 409

    # Unknown export id: 404.
    response = await client.get("/api/v1/exports/" + "exp_" + "0" * 32)
    assert response.status_code == 404
    response = await client.get("/api/v1/exports/" + "exp_" + "0" * 32 + "/download")
    assert response.status_code == 404
