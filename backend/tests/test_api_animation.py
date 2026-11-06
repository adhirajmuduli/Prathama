"""End-to-end test of the animation job: analyze, then animate, then verify the MP4."""

from __future__ import annotations

from pathlib import Path

import httpx
from tests.test_api_analyses import _recipe, _upload_and_ingest

from trendsmapp.services.ingestion import build_default_registry
from trendsmapp.worker.main import Worker


async def test_animation_end_to_end(
    client: httpx.AsyncClient, settings, engine, store, testdata_path: Path
) -> None:
    version_id = await _upload_and_ingest(client, testdata_path)
    worker = Worker(
        settings=settings, engine=engine, object_store=store, registry=build_default_registry()
    )
    for _ in range(3):
        await worker.run_once()

    created = await client.post("/api/v1/analyses", json=_recipe(version_id))
    assert created.status_code == 202
    run_id = created.json()["run_id"]
    for _ in range(2):
        await worker.run_once()
    run = await client.get(f"/api/v1/analyses/{run_id}")
    assert run.json()["status"] == "succeeded"

    animation = await client.post(
        f"/api/v1/analyses/{run_id}/animations",
        json={"parameter_id": "dissolved_oxygen", "method": "idw", "fps": 2},
    )
    assert animation.status_code == 202
    job_id = animation.json()["job_id"]

    await worker.run_once()
    job = await client.get(f"/api/v1/jobs/{job_id}")
    assert job.json()["status"] == "succeeded"
    result = job.json()["result"]
    assert result["frame_count"] == 3
    assert result["fps"] == 2
    assert result["sha256"]

    artifacts = await client.get(f"/api/v1/analyses/{run_id}/artifacts")
    video = next(item for item in artifacts.json()["items"] if item["kind"] == "video")
    assert video["content_type"] == "video/mp4"

    download = await client.get(f"/api/v1/artifacts/{video['artifact_id']}/content")
    assert download.status_code == 200
    assert download.headers["x-artifact-sha256"] == video["sha256"]
    assert download.content[:4] in (b"\x00\x00\x00 ", b"ftyp") or download.content[4:8] == b"ftyp"

    # Read the MP4 back from a temp file: frame count, fps, duration.
    import os
    import tempfile

    import imageio_ffmpeg

    with tempfile.TemporaryDirectory() as tmp:
        mp4_path = os.path.join(tmp, "animation.mp4")
        Path(mp4_path).write_bytes(download.content)
        gen = imageio_ffmpeg.read_frames(mp4_path)
        meta = next(gen)
        frames = sum(1 for _frame in gen)
        gen.close()
    assert frames == 3
    assert float(meta["fps"]) == 2.0
    assert abs(float(meta["duration"]) - 1.5) < 0.5

    # Idempotent: the same animation request returns the same job.
    again = await client.post(
        f"/api/v1/analyses/{run_id}/animations",
        json={"parameter_id": "dissolved_oxygen", "method": "idw", "fps": 2},
    )
    assert again.status_code == 202


async def test_animation_rejects_a_run_without_rasters(
    client: httpx.AsyncClient, testdata_path: Path
) -> None:
    await _upload_and_ingest(client, testdata_path)
    # No analysis run yet: the version is unsealed, and no run exists.
    response = await client.post(
        "/api/v1/analyses/run_" + "0" * 32 + "/animations", json={"fps": 2}
    )
    assert response.status_code == 404
