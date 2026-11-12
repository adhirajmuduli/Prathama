"""End-to-end tests for the PDF report API and the report worker job."""

from __future__ import annotations

from pathlib import Path

import httpx

from trendsmapp.domain.enums import JobType
from trendsmapp.hashing import sha256_bytes
from trendsmapp.services.ingestion import build_default_registry
from trendsmapp.worker.main import Worker


async def _upload_and_ingest(client: httpx.AsyncClient, testdata_path: Path) -> str:
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
    upload_id = create.json()["upload_id"]
    await client.put(f"/api/v1/uploads/{upload_id}/parts/1", content=payload)
    await client.post(f"/api/v1/uploads/{upload_id}/complete")
    probe = await client.post(f"/api/v1/uploads/{upload_id}/probe")
    created = await client.post(
        "/api/v1/datasets",
        json={
            "upload_id": upload_id,
            "name": "report pilot",
            "mapping": probe.json()["proposed_mapping"],
        },
    )
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


def test_default_registry_registers_report_handler() -> None:
    assert build_default_registry().supports(JobType.REPORT)


async def test_report_end_to_end(
    client: httpx.AsyncClient, settings, engine, store, testdata_path: Path
) -> None:
    version_id = await _upload_and_ingest(client, testdata_path)
    worker = Worker(
        settings=settings, engine=engine, object_store=store, registry=build_default_registry()
    )
    for _ in range(3):
        await worker.run_once()
    assert (await client.get(f"/api/v1/dataset-versions/{version_id}")).json()["sealed"] is True

    created = await client.post("/api/v1/analyses", json=_recipe(version_id))
    run_id = created.json()["run_id"]
    for _ in range(2):
        await worker.run_once()
    assert (await client.get(f"/api/v1/analyses/{run_id}")).json()["status"] == "succeeded"

    report = await client.post("/api/v1/reports", json={"run_id": run_id})
    assert report.status_code == 202
    body = report.json()
    report_id = body["report_id"]
    assert report_id.startswith("rpt_")

    # Idempotent per run.
    again = await client.post("/api/v1/reports", json={"run_id": run_id})
    assert again.json()["report_id"] == report_id

    for _ in range(2):
        await worker.run_once()  # the report job

    found = await client.get(f"/api/v1/reports/{report_id}")
    assert found.status_code == 200
    report_body = found.json()
    assert report_body["run_id"] == run_id
    assert report_body["status"] == "succeeded"
    assert report_body["artifact"]["kind"] == "report"
    assert report_body["artifact"]["content_type"] == "application/pdf"
    assert report_body["summary"]["artifacts"] > 0

    download = await client.get(f"/api/v1/reports/{report_id}/download")
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("application/pdf")
    assert download.headers["x-artifact-sha256"] == report_body["artifact"]["sha256"]
    assert download.content.startswith(b"%PDF-")
    assert download.content.rstrip().endswith(b"%%EOF")


async def test_report_rejects_bad_requests(
    client: httpx.AsyncClient, settings, engine, store, testdata_path: Path
) -> None:
    response = await client.post("/api/v1/reports", json={"run_id": "run_" + "0" * 32})
    assert response.status_code == 404

    version_id = await _upload_and_ingest(client, testdata_path)
    worker = Worker(
        settings=settings, engine=engine, object_store=store, registry=build_default_registry()
    )
    for _ in range(3):
        await worker.run_once()
    created = await client.post("/api/v1/analyses", json=_recipe(version_id))
    run_id = created.json()["run_id"]
    # Run not succeeded yet: 409.
    response = await client.post("/api/v1/reports", json={"run_id": run_id})
    assert response.status_code == 409

    response = await client.get("/api/v1/reports/" + "rpt_" + "0" * 32)
    assert response.status_code == 404
    response = await client.get("/api/v1/reports/" + "rpt_" + "0" * 32 + "/download")
    assert response.status_code == 404
