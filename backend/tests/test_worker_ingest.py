"""End-to-end test: upload to sealed dataset version through the real worker."""

from __future__ import annotations

import io
from pathlib import Path

import httpx
import pyarrow.parquet as pq
import pytest

from trendsmapp.services.ingestion import build_default_registry
from trendsmapp.worker.main import Worker


async def test_end_to_end_ingest(
    client: httpx.AsyncClient,
    settings,
    engine,
    store,
    testdata_path: Path,
) -> None:
    payload = testdata_path("long_observations.csv").read_bytes()

    create = await client.post(
        "/api/v1/uploads",
        json={
            "filename": "long_observations.csv",
            "content_type": "text/csv",
            "size_bytes": len(payload),
        },
    )
    assert create.status_code == 201
    upload_id = create.json()["upload_id"]
    put = await client.put(f"/api/v1/uploads/{upload_id}/parts/1", content=payload)
    assert put.status_code == 200
    complete = await client.post(f"/api/v1/uploads/{upload_id}/complete")
    assert complete.status_code == 200
    probe_job_id = complete.json()["job_id"]

    probe = await client.post(f"/api/v1/uploads/{upload_id}/probe")
    assert probe.status_code == 200
    probe_body = probe.json()
    assert probe_body["file_format"] == "csv"
    assert probe_body["layout"] == "long"
    assert probe_body["fields"][0] == "station"
    assert probe_body["proposed_mapping"]["layout"] == "long"

    create_ds = await client.post(
        "/api/v1/datasets",
        json={
            "upload_id": upload_id,
            "name": "Chilika pilot",
            "mapping": probe_body["proposed_mapping"],
        },
    )
    assert create_ds.status_code == 202
    created = create_ds.json()
    dataset_id = created["dataset_id"]
    version_id = created["version_id"]
    ingest_job_id = created["job_id"]

    bad = await client.post(
        "/api/v1/datasets",
        json={
            "upload_id": upload_id,
            "name": "broken",
            "mapping": {**probe_body["proposed_mapping"], "columns": []},
        },
    )
    assert bad.status_code == 422

    worker = Worker(
        settings=settings,
        engine=engine,
        object_store=store,
        registry=build_default_registry(),
    )
    assert await worker.run_once() is True
    assert await worker.run_once() is True

    probe_job = await client.get(f"/api/v1/jobs/{probe_job_id}")
    assert probe_job.json()["status"] == "succeeded"
    assert probe_job.json()["result"]["stage"] == "probed"

    job = await client.get(f"/api/v1/jobs/{ingest_job_id}")
    assert job.status_code == 200
    job_body = job.json()
    assert job_body["status"] == "succeeded"
    assert job_body["result"]["dataset_version_id"] == version_id
    assert job_body["result"]["observation_count"] == 12
    assert job_body["result"]["qc"]["flagged_count"] >= 1

    version = await client.get(f"/api/v1/dataset-versions/{version_id}")
    assert version.status_code == 200
    version_body = version.json()
    assert version_body["sealed"] is True
    assert version_body["row_count"] == 12
    assert version_body["station_count"] == 2
    assert version_body["parameter_count"] == 2
    assert version_body["boundary_id"] == "relation/1917079"
    kinds = {item["kind"] for item in version_body["artifacts"]}
    assert {
        "normalized_dataset",
        "parse_report",
        "normalization_report",
        "qc_report",
    } <= kinds
    assert version_body["normalized_artifact"]["sha256"]

    dataset = await client.get(f"/api/v1/datasets/{dataset_id}")
    assert dataset.json()["current_version_id"] == version_id
    versions = await client.get(f"/api/v1/datasets/{dataset_id}/versions")
    assert len(versions.json()["items"]) == 1

    preview = await client.get(
        f"/api/v1/dataset-versions/{version_id}/preview", params={"limit": 5}
    )
    assert preview.status_code == 200
    preview_body = preview.json()
    assert preview_body["row_count"] == 12
    assert len(preview_body["rows"]) == 5
    assert "observation_id" in preview_body["columns"]
    assert "canonical_value" in preview_body["columns"]

    qc_report = await client.get(f"/api/v1/dataset-versions/{version_id}/reports/qc")
    assert qc_report.status_code == 200
    assert qc_report.json()["observation_count"] == 12
    assert qc_report.json()["flags"]

    parse_report = await client.get(f"/api/v1/dataset-versions/{version_id}/reports/parse")
    assert parse_report.json()["row_count"] == 12
    assert parse_report.json()["layout"] == "long"

    provenance = await client.get(f"/api/v1/dataset-versions/{version_id}/provenance")
    assert provenance.status_code == 200
    items = provenance.json()["items"]
    assert len(items) == 1
    assert items[0]["event_type"] == "ingest"
    assert items[0]["parent_artifact_ids"]

    normalized = next(
        item for item in version_body["artifacts"] if item["kind"] == "normalized_dataset"
    )
    content = await client.get(f"/api/v1/artifacts/{normalized['artifact_id']}/content")
    assert content.status_code == 200
    assert content.headers["x-artifact-sha256"] == normalized["sha256"]
    assert len(content.content) == normalized["size_bytes"]
    parquet = pq.ParquetFile(io.BytesIO(content.content))
    assert parquet.metadata.num_rows == 12
    table = parquet.read()
    assert table.column_names[0] == "observation_id"
    censored = [row for row in table.to_pylist() if row["raw_value"] == "<0.01"]
    assert len(censored) == 1
    assert censored[0]["canonical_value"] is None
    assert censored[0]["detection_limit"] == pytest.approx(0.01)
    assert censored[0]["value_qualifier"] == "below_detection_limit"


async def test_ingest_job_fails_cleanly_without_a_mapping_version(
    client: httpx.AsyncClient,
    settings,
    engine,
    store,
    session_factory,
    testdata_path: Path,
) -> None:
    """A dataset job whose version row was deleted fails with a structured error."""
    from sqlalchemy import delete

    from trendsmapp.persistence.database import session_scope
    from trendsmapp.persistence.models import DatasetVersionRow

    payload = testdata_path("long_observations.csv").read_bytes()
    create = await client.post(
        "/api/v1/uploads", json={"filename": "long_observations.csv", "size_bytes": len(payload)}
    )
    upload_id = create.json()["upload_id"]
    await client.put(f"/api/v1/uploads/{upload_id}/parts/1", content=payload)
    await client.post(f"/api/v1/uploads/{upload_id}/complete")
    probe = await client.post(f"/api/v1/uploads/{upload_id}/probe")
    created = await client.post(
        "/api/v1/datasets",
        json={
            "upload_id": upload_id,
            "name": "doomed",
            "mapping": probe.json()["proposed_mapping"],
        },
    )
    version_id = created.json()["version_id"]
    job_id = created.json()["job_id"]

    async with session_scope(session_factory) as session:
        await session.execute(delete(DatasetVersionRow).where(DatasetVersionRow.id == version_id))

    worker = Worker(
        settings=settings, engine=engine, object_store=store, registry=build_default_registry()
    )
    await worker.run_once()  # probe-only job
    await worker.run_once()  # dataset job, now failing
    job = await client.get(f"/api/v1/jobs/{job_id}")
    body = job.json()
    assert body["status"] == "failed"
    assert body["error"]["code"] == "not_found"
    assert "dataset version" in body["error"]["message"]
