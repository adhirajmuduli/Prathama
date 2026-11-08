"""End-to-end test for scripts/reproduce_run.py against a real export bundle."""

from __future__ import annotations

import math
from pathlib import Path

import httpx
from scripts.reproduce_run import reproduce

from trendsmapp.hashing import sha256_bytes
from trendsmapp.services.ingestion import build_default_registry
from trendsmapp.worker.main import Worker

_STATIONS = (
    ("St. A", 19.7350, 85.4700),
    ("St. B", 19.8100, 85.5200),
    ("St. C", 19.7500, 85.4900),
    ("St. D", 19.7000, 85.4500),
    ("St. E", 19.7800, 85.5000),
    ("St. F", 19.7200, 85.4600),
)


def _ml_fixture_csv() -> bytes:
    lines = ["station,latitude,longitude,sampled_at,parameter,value,unit,qualifier,depth_m,notes"]
    for station_index, (name, lat, lon) in enumerate(_STATIONS):
        for month in range(1, 13):
            value = 6.5 + 0.4 * math.sin(month / 12.0 * 2.0 * math.pi) + 0.05 * station_index
            stamp = f"2024-{month:02d}-15T09:30:00Z"
            lines.append(
                f"{name},{lat:.4f},{lon:.4f},{stamp},dissolved_oxygen,{value:.3f},mg/L,,0.5,"
            )
    return ("\n".join(lines) + "\n").encode("utf-8")


async def _sealed_version(client: httpx.AsyncClient, settings, engine, store) -> str:
    payload = _ml_fixture_csv()
    create = await client.post(
        "/api/v1/uploads",
        json={
            "filename": "ml_fixture.csv",
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
            "name": "reproduce pilot",
            "mapping": probe.json()["proposed_mapping"],
        },
    )
    version_id = created.json()["version_id"]
    worker = Worker(
        settings=settings, engine=engine, object_store=store, registry=build_default_registry()
    )
    for _ in range(3):
        await worker.run_once()
    assert (await client.get(f"/api/v1/dataset-versions/{version_id}")).json()["sealed"] is True
    return version_id


async def _exported_bundle(
    client: httpx.AsyncClient, settings, engine, store, tmp_path: Path
) -> Path:
    version_id = await _sealed_version(client, settings, engine, store)
    task = {
        "schema_version": "1.0.0",
        "dataset_version_id": version_id,
        "target_parameter_id": "dissolved_oxygen",
        "prediction_unit": "mg/L",
        "setting": "known_station_temporal",
        "outer_split": "station_group",
        "inner_split": "station_group",
        "candidate_models": ["elastic_net"],
        "search_budget": 1,
        "primary_metric": "rmse",
        "seed": 3,
        "uncertainty_method": "quantile",
        "explanation_methods": ["permutation"],
    }
    created = await client.post("/api/v1/model-runs", json=task)
    run_id = created.json()["run_id"]
    worker = Worker(
        settings=settings, engine=engine, object_store=store, registry=build_default_registry()
    )
    for _ in range(2):
        await worker.run_once()  # train
    assert (await client.get(f"/api/v1/model-runs/{run_id}")).json()["status"] == "succeeded"

    export = await client.post("/api/v1/exports", json={"run_id": run_id})
    export_id = export.json()["export_id"]
    for _ in range(2):
        await worker.run_once()  # export
    download = await client.get(f"/api/v1/exports/{export_id}/download")
    assert download.status_code == 200
    bundle = tmp_path / "bundle.zip"
    bundle.write_bytes(download.content)
    return bundle


async def test_reproduce_exported_model_run_matches(
    client: httpx.AsyncClient, settings, engine, store, tmp_path: Path
) -> None:
    bundle = await _exported_bundle(client, settings, engine, store, tmp_path)
    report = await reproduce(
        bundle_path=bundle,
        database_url=settings.database_url,
        storage_root=settings.local_storage_root,
    )
    assert report["ok"] is True, report
    assert report["checked_metrics"] > 0


async def test_reproduce_rejects_a_tampered_bundle(
    client: httpx.AsyncClient, settings, engine, store, tmp_path: Path
) -> None:
    import io
    import zipfile

    bundle = await _exported_bundle(client, settings, engine, store, tmp_path)
    payload = bundle.read_bytes()
    buffer = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    members["README.md"] = b"# tampered\n"
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    tampered = tmp_path / "tampered.zip"
    tampered.write_bytes(buffer.getvalue())
    report = await reproduce(
        bundle_path=tampered,
        database_url=settings.database_url,
        storage_root=settings.local_storage_root,
    )
    assert report["ok"] is False
    assert report["stage"] == "bundle-verification"
