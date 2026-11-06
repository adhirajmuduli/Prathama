"""End-to-end tests for the analyses API and the analyze worker job."""

from __future__ import annotations

from pathlib import Path

import httpx

from trendsmapp.hashing import sha256_bytes
from trendsmapp.services.ingestion import build_default_registry
from trendsmapp.worker.main import Worker


async def _upload_and_ingest(client: httpx.AsyncClient, testdata_path: Path) -> str:
    """Upload the multi-station long fixture, create a dataset, and return the version id."""
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
    probe_body = probe.json()
    assert probe_body["layout"] == "long"
    mapping = probe_body["proposed_mapping"]

    created = await client.post(
        "/api/v1/datasets",
        json={"upload_id": upload_id, "name": "multi-station pilot", "mapping": mapping},
    )
    assert created.status_code == 202
    return created.json()["version_id"]


def _recipe(version_id: str, **overrides: object) -> dict:
    recipe: dict = {
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
    for key, value in overrides.items():
        recipe[key] = value
    return recipe


async def test_analysis_end_to_end(
    client: httpx.AsyncClient, settings, engine, store, testdata_path: Path
) -> None:
    version_id = await _upload_and_ingest(client, testdata_path)

    worker = Worker(
        settings=settings, engine=engine, object_store=store, registry=build_default_registry()
    )
    for _ in range(3):
        await worker.run_once()  # probe-only job, then the ingest job

    version = await client.get(f"/api/v1/dataset-versions/{version_id}")
    assert version.json()["sealed"] is True

    created = await client.post("/api/v1/analyses", json=_recipe(version_id))
    assert created.status_code == 202
    body = created.json()
    run_id = body["run_id"]
    recipe_hash = body["recipe_hash"]
    assert recipe_hash
    assert len(recipe_hash) == 64

    for _ in range(2):
        await worker.run_once()  # the analyze job

    run = await client.get(f"/api/v1/analyses/{run_id}")
    assert run.status_code == 200
    assert run.json()["status"] == "succeeded"
    assert run.json()["recipe_hash"] == recipe_hash

    results = await client.get(f"/api/v1/analyses/{run_id}/results")
    assert results.status_code == 200
    summary = results.json()
    assert len(summary["frames"]) == 3  # three timestamps
    for frame in summary["frames"]:
        assert frame["point_count"] == 4  # four stations
        assert frame["methods"][0]["method"] == "idw"
        assert frame["methods"][0]["rmse"] is not None
        assert frame["methods"][0]["folds"] == 4  # one fold per station
        assert frame["decisions"][0]["selected"] == "idw"
    assert summary["temporal"]["series"]
    assert summary["temporal"]["series"][0]["trend_slope_per_day"] is not None

    artifacts = await client.get(f"/api/v1/analyses/{run_id}/artifacts")
    assert artifacts.status_code == 200
    kinds = {item["kind"] for item in artifacts.json()["items"]}
    assert "metrics" in kinds  # the results summary
    assert "raster" in kinds  # geotiff/png surfaces

    # Raster artifacts are downloadable with a verified digest header.
    items = artifacts.json()["items"]
    geotiff = next(item for item in items if item["media_type_detail"].get("kind") == "geotiff")
    download = await client.get(f"/api/v1/artifacts/{geotiff['artifact_id']}/content")
    assert download.status_code == 200
    assert download.headers["x-artifact-sha256"] == geotiff["sha256"]
    assert download.content[:4] in (b"II*\x00", b"MM\x00*")  # TIFF magic


async def test_analysis_rejects_unsealed_version_and_bad_recipes(
    client: httpx.AsyncClient, settings, engine, store, testdata_path: Path
) -> None:
    version_id = await _upload_and_ingest(client, testdata_path)

    # Unsealed version: rejected before any job is enqueued.
    response = await client.post("/api/v1/analyses", json=_recipe(version_id))
    assert response.status_code == 409

    worker = Worker(
        settings=settings, engine=engine, object_store=store, registry=build_default_registry()
    )
    for _ in range(3):
        await worker.run_once()

    bad_method = _recipe(version_id)
    bad_method["spatial"]["methods"] = [{"method": "kde"}]
    response = await client.post("/api/v1/analyses", json=bad_method)
    assert response.status_code == 422

    response = await client.post("/api/v1/analyses", json=_recipe("dsv_" + "0" * 32))
    assert response.status_code == 404


async def test_same_recipe_is_idempotent(
    client: httpx.AsyncClient, settings, engine, store, testdata_path: Path
) -> None:
    version_id = await _upload_and_ingest(client, testdata_path)
    worker = Worker(
        settings=settings, engine=engine, object_store=store, registry=build_default_registry()
    )
    for _ in range(3):
        await worker.run_once()

    first = await client.post("/api/v1/analyses", json=_recipe(version_id))
    second = await client.post("/api/v1/analyses", json=_recipe(version_id))
    assert first.status_code == second.status_code == 202
    assert first.json()["run_id"] == second.json()["run_id"]
    assert first.json()["recipe_hash"] == second.json()["recipe_hash"]
