"""End-to-end tests for the model-runs API and the train worker job."""

from __future__ import annotations

import math
from pathlib import Path

import httpx

from trendsmapp.domain.enums import JobType
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
    """Build a deterministic 6-station x 12-month long-format CSV."""
    lines = ["station,latitude,longitude,sampled_at,parameter,value,unit,qualifier,depth_m,notes"]
    for station_index, (name, lat, lon) in enumerate(_STATIONS):
        for month in range(1, 13):
            value = 6.5 + 0.4 * math.sin(month / 12.0 * 2.0 * math.pi) + 0.05 * station_index
            stamp = f"2024-{month:02d}-15T09:30:00Z"
            lines.append(
                f"{name},{lat:.4f},{lon:.4f},{stamp},dissolved_oxygen,{value:.3f},mg/L,,0.5,"
            )
    return ("\n".join(lines) + "\n").encode("utf-8")


async def _upload_and_ingest(client: httpx.AsyncClient) -> str:
    """Upload the generated ML fixture, create a dataset, and return the version id."""
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
    assert create.status_code == 201
    upload_id = create.json()["upload_id"]
    put = await client.put(f"/api/v1/uploads/{upload_id}/parts/1", content=payload)
    assert put.status_code == 200
    complete = await client.post(f"/api/v1/uploads/{upload_id}/complete")
    assert complete.status_code == 200

    probe = await client.post(f"/api/v1/uploads/{upload_id}/probe")
    assert probe.status_code == 200
    mapping = probe.json()["proposed_mapping"]

    created = await client.post(
        "/api/v1/datasets",
        json={"upload_id": upload_id, "name": "ml pilot", "mapping": mapping},
    )
    assert created.status_code == 202
    return created.json()["version_id"]


async def _seal(client: httpx.AsyncClient, settings, engine, store) -> str:
    """Run the worker until the dataset version of the fixture is sealed."""
    version_id = await _upload_and_ingest(client)
    worker = Worker(
        settings=settings, engine=engine, object_store=store, registry=build_default_registry()
    )
    for _ in range(3):
        await worker.run_once()
    version = await client.get(f"/api/v1/dataset-versions/{version_id}")
    assert version.json()["sealed"] is True
    return version_id


def _task(version_id: str, **overrides: object) -> dict:
    task: dict = {
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
        "uncertainty_method": "bootstrap_ensemble",
        "explanation_methods": ["permutation"],
    }
    for key, value in overrides.items():
        task[key] = value
    return task


def test_default_registry_registers_train_handler() -> None:
    """The default worker registry must know the train job type."""
    registry = build_default_registry()
    assert registry.supports(JobType.TRAIN)


async def test_model_run_end_to_end(
    client: httpx.AsyncClient, settings, engine, store, testdata_path: Path
) -> None:
    version_id = await _seal(client, settings, engine, store)

    created = await client.post("/api/v1/model-runs", json=_task(version_id))
    assert created.status_code == 202
    body = created.json()
    run_id = body["run_id"]
    assert body["job_id"]
    assert len(body["task_hash"]) == 64
    assert body["status"] == "accepted"

    # Reposting the identical task returns the same run (idempotent).
    again = await client.post("/api/v1/model-runs", json=_task(version_id))
    assert again.status_code == 202
    assert again.json()["run_id"] == run_id

    worker = Worker(
        settings=settings, engine=engine, object_store=store, registry=build_default_registry()
    )
    for _ in range(2):
        await worker.run_once()  # the train job

    run = await client.get(f"/api/v1/model-runs/{run_id}")
    assert run.status_code == 200
    run_body = run.json()
    assert run_body["status"] == "succeeded"
    assert run_body["task"]["target_parameter_id"] == "dissolved_oxygen"
    assert run_body["task_hash"] == body["task_hash"]
    assert run_body["results"] is not None
    assert run_body["explanations"] is not None

    metrics = await client.get(f"/api/v1/model-runs/{run_id}/metrics")
    assert metrics.status_code == 200
    metrics_body = metrics.json()
    assert metrics_body["schema_version"] == "1.0.0"
    assert metrics_body["run_id"] == run_id
    assert metrics_body["rows"] == 72
    assert "elastic_net" in metrics_body["aggregated"]
    assert "mean_baseline" in metrics_body["baseline_comparison"]
    assert metrics_body["uncertainty"]["method"] == "bootstrap_ensemble"
    assert metrics_body["selected_family"] in {"elastic_net"}

    folds = await client.get(f"/api/v1/model-runs/{run_id}/folds")
    assert folds.status_code == 200
    fold_list = folds.json()["folds"]
    assert fold_list
    assert all("rmse" in fold["metrics"] for fold in fold_list)

    predictions = await client.get(f"/api/v1/model-runs/{run_id}/predictions")
    assert predictions.status_code == 200
    prediction_folds = predictions.json()["folds"]
    assert prediction_folds
    held_out = 0
    for fold in prediction_folds:
        assert len(fold["y_true"]) == len(fold["y_pred"]) == fold["test_size"]
        held_out += fold["test_size"]
    # Every family holds out each of the 72 rows exactly once per its folds.
    assert held_out > 0
    assert held_out % 72 == 0

    explanations = await client.get(f"/api/v1/model-runs/{run_id}/explanations")
    assert explanations.status_code == 200
    explanation_body = explanations.json()
    assert explanation_body["run_id"] == run_id
    assert explanation_body["model_family"] == "elastic_net"
    assert explanation_body["rows"]
    assert explanation_body["held_out_rows"] > 0

    artifacts = await client.get(f"/api/v1/model-runs/{run_id}/artifacts")
    assert artifacts.status_code == 200
    kinds = {item["kind"] for item in artifacts.json()["items"]}
    assert {"model", "metrics", "predictions", "explanations"} <= kinds


async def test_model_run_rejects_unsealed_and_unknown_versions(
    client: httpx.AsyncClient, settings, engine, store
) -> None:
    version_id = await _upload_and_ingest(client)

    response = await client.post("/api/v1/model-runs", json=_task(version_id))
    assert response.status_code == 409

    response = await client.post("/api/v1/model-runs", json=_task("dsv_" + "0" * 32))
    assert response.status_code == 404


async def test_model_run_rejects_incompatible_split(
    client: httpx.AsyncClient, settings, engine, store
) -> None:
    version_id = await _seal(client, settings, engine, store)

    # Random row splitting is not a valid evaluation for an unseen-station claim.
    bad = _task(
        version_id,
        setting="unseen_station_spatial",
        outer_split="random_row",
        inner_split="random_row",
    )
    response = await client.post("/api/v1/model-runs", json=bad)
    assert response.status_code == 422

    # Unknown extra fields are rejected so a typo can never change the science.
    unknown_field = _task(version_id)
    unknown_field["n_estimators"] = 100
    response = await client.post("/api/v1/model-runs", json=unknown_field)
    assert response.status_code == 422
