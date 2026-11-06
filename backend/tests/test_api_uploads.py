"""API tests for the chunked upload flow and the job endpoints."""

from __future__ import annotations

from pathlib import Path

import httpx

from trendsmapp.hashing import sha256_bytes


def _large_csv(row_count: int = 40_000) -> bytes:
    """Build a deterministic CSV larger than one 1 MiB chunk."""
    header = "station,latitude,longitude,sampled_at,parameter,value,unit,qualifier,depth_m,notes\n"
    row = "St. A,19.7350,85.4700,2024-01-15T09:30:00Z,dissolved_oxygen,6.8,mg/L,,0.5,\n"
    return (header + row * row_count).encode("utf-8")


async def test_create_upload_session_returns_the_part_plan(client: httpx.AsyncClient) -> None:
    payload = b"station,value\nSt. A,1\n"
    response = await client.post(
        "/api/v1/uploads",
        json={
            "filename": "observations.csv",
            "content_type": "text/csv",
            "size_bytes": len(payload),
            "sha256": sha256_bytes(payload),
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["upload_id"].startswith("upl_")
    assert body["extension"] == ".csv"
    assert body["part_count"] == 1
    assert body["parts"] == [
        {
            "part_number": 1,
            "start_byte": 0,
            "end_byte": len(payload) - 1,
            "size_bytes": len(payload),
        }
    ]
    assert body["status"] == "open"


async def test_create_upload_rejects_an_unsupported_extension(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/uploads",
        json={"filename": "data.json", "size_bytes": 10},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_create_upload_rejects_oversize_files(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/uploads",
        json={"filename": "big.csv", "size_bytes": 200 * 1024 * 1024},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "resource_limit_exceeded"


async def test_create_upload_rejects_an_out_of_bounds_chunk_size(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/uploads",
        json={"filename": "a.csv", "size_bytes": 10, "chunk_size_bytes": 1024},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert "bounds" in body["error"]["details"]


async def test_full_upload_flow_stores_the_raw_artifact_and_enqueues_ingest(
    client: httpx.AsyncClient, testdata_path: Path
) -> None:
    payload = testdata_path("long_observations.csv").read_bytes()
    digest = sha256_bytes(payload)
    create = await client.post(
        "/api/v1/uploads",
        json={
            "filename": "long_observations.csv",
            "content_type": "text/csv",
            "size_bytes": len(payload),
            "sha256": digest,
        },
    )
    assert create.status_code == 201
    upload_id = create.json()["upload_id"]

    part = await client.put(
        f"/api/v1/uploads/{upload_id}/parts/1",
        content=payload,
        headers={"Content-Range": f"bytes 0-{len(payload) - 1}"},
    )
    assert part.status_code == 200
    assert part.json()["sha256"] == digest
    assert part.json()["received"] is True

    status_response = await client.get(f"/api/v1/uploads/{upload_id}")
    assert status_response.status_code == 200
    status_body = status_response.json()
    assert status_body["parts_received"] == [1]
    assert status_body["missing_parts"] == []

    complete = await client.post(
        f"/api/v1/uploads/{upload_id}/complete",
        headers={"Idempotency-Key": "idem-1"},
    )
    assert complete.status_code == 200
    done = complete.json()
    assert done["status"] == "completed"
    assert done["artifact"]["kind"] == "raw_upload"
    assert done["artifact"]["sha256"] == digest
    assert done["artifact"]["size_bytes"] == len(payload)
    job_id = done["job_id"]
    assert job_id.startswith("job_")

    status_after = await client.get(f"/api/v1/uploads/{upload_id}")
    assert status_after.json()["status"] == "completed"
    assert status_after.json()["artifact"]["artifact_id"] == done["artifact"]["artifact_id"]
    assert status_after.json()["job_id"] == job_id

    job = await client.get(f"/api/v1/jobs/{job_id}")
    assert job.status_code == 200
    job_body = job.json()
    assert job_body["job_type"] == "ingest"
    assert job_body["status"] == "queued"
    assert job_body["payload"]["upload_id"] == upload_id
    assert job_body["payload"]["sha256"] == digest


async def test_complete_is_idempotent_for_the_same_key(
    client: httpx.AsyncClient, testdata_path: Path
) -> None:
    payload = testdata_path("long_observations.csv").read_bytes()
    create = await client.post(
        "/api/v1/uploads",
        json={
            "filename": "long_observations.csv",
            "size_bytes": len(payload),
            "sha256": sha256_bytes(payload),
        },
    )
    upload_id = create.json()["upload_id"]
    await client.put(f"/api/v1/uploads/{upload_id}/parts/1", content=payload)
    first = await client.post(
        f"/api/v1/uploads/{upload_id}/complete", headers={"Idempotency-Key": "k1"}
    )
    second = await client.post(
        f"/api/v1/uploads/{upload_id}/complete", headers={"Idempotency-Key": "k1"}
    )
    assert first.status_code == second.status_code == 200
    assert first.json()["job_id"] == second.json()["job_id"]
    assert first.json()["artifact"]["artifact_id"] == second.json()["artifact"]["artifact_id"]


async def test_multi_part_upload_assembles_in_order(client: httpx.AsyncClient) -> None:
    payload = _large_csv()
    digest = sha256_bytes(payload)
    chunk = 1024 * 1024
    create = await client.post(
        "/api/v1/uploads",
        json={
            "filename": "large.csv",
            "content_type": "text/csv",
            "size_bytes": len(payload),
            "sha256": digest,
            "chunk_size_bytes": chunk,
        },
    )
    assert create.status_code == 201
    body = create.json()
    assert body["part_count"] == (len(payload) + chunk - 1) // chunk
    upload_id = body["upload_id"]

    for plan in body["parts"]:
        start = plan["start_byte"]
        end = plan["end_byte"]
        part = await client.put(
            f"/api/v1/uploads/{upload_id}/parts/{plan['part_number']}",
            content=payload[start : end + 1],
            headers={"Content-Range": f"bytes {start}-{end}"},
        )
        assert part.status_code == 200, plan["part_number"]

    complete = await client.post(f"/api/v1/uploads/{upload_id}/complete")
    assert complete.status_code == 200
    assert complete.json()["artifact"]["sha256"] == digest
    assert complete.json()["artifact"]["size_bytes"] == len(payload)


async def test_complete_rejects_missing_parts(client: httpx.AsyncClient) -> None:
    payload = _large_csv()
    create = await client.post(
        "/api/v1/uploads",
        json={"filename": "large.csv", "size_bytes": len(payload), "chunk_size_bytes": 1024 * 1024},
    )
    upload_id = create.json()["upload_id"]
    await client.put(f"/api/v1/uploads/{upload_id}/parts/1", content=payload[: 1024 * 1024])
    complete = await client.post(f"/api/v1/uploads/{upload_id}/complete")
    assert complete.status_code == 422
    details = complete.json()["error"]["details"]
    assert details["missing_parts"]


async def test_complete_rejects_a_tampered_declared_digest(
    client: httpx.AsyncClient, testdata_path: Path
) -> None:
    payload = testdata_path("long_observations.csv").read_bytes()
    create = await client.post(
        "/api/v1/uploads",
        json={
            "filename": "long_observations.csv",
            "size_bytes": len(payload),
            "sha256": "f" * 64,
        },
    )
    upload_id = create.json()["upload_id"]
    await client.put(f"/api/v1/uploads/{upload_id}/parts/1", content=payload)
    complete = await client.post(f"/api/v1/uploads/{upload_id}/complete")
    assert complete.status_code == 409
    assert complete.json()["error"]["code"] == "conflict"


async def test_put_part_rejects_a_wrong_size_and_a_mismatched_range(
    client: httpx.AsyncClient, testdata_path: Path
) -> None:
    payload = testdata_path("long_observations.csv").read_bytes()
    create = await client.post(
        "/api/v1/uploads",
        json={"filename": "long_observations.csv", "size_bytes": len(payload)},
    )
    upload_id = create.json()["upload_id"]

    wrong_size = await client.put(f"/api/v1/uploads/{upload_id}/parts/1", content=payload[:-1])
    assert wrong_size.status_code == 422

    wrong_range = await client.put(
        f"/api/v1/uploads/{upload_id}/parts/1",
        content=payload,
        headers={"Content-Range": "bytes 10-99"},
    )
    assert wrong_range.status_code == 422
    assert "expected_range" in wrong_range.json()["error"]["details"]

    out_of_range = await client.put(f"/api/v1/uploads/{upload_id}/parts/9", content=payload)
    assert out_of_range.status_code == 422


async def test_abort_cancels_an_open_session_and_deletes_parts(
    client: httpx.AsyncClient, testdata_path: Path
) -> None:
    payload = testdata_path("long_observations.csv").read_bytes()
    create = await client.post(
        "/api/v1/uploads", json={"filename": "long_observations.csv", "size_bytes": len(payload)}
    )
    upload_id = create.json()["upload_id"]
    await client.put(f"/api/v1/uploads/{upload_id}/parts/1", content=payload)
    abort = await client.post(f"/api/v1/uploads/{upload_id}/abort")
    assert abort.status_code == 200
    assert abort.json()["status"] == "cancelled"

    status_response = await client.get(f"/api/v1/uploads/{upload_id}")
    assert status_response.json()["status"] == "cancelled"
    assert status_response.json()["parts_received"] == []

    again = await client.post(f"/api/v1/uploads/{upload_id}/abort")
    assert again.status_code == 409


async def test_abort_refuses_a_completed_upload(
    client: httpx.AsyncClient, testdata_path: Path
) -> None:
    payload = testdata_path("long_observations.csv").read_bytes()
    create = await client.post(
        "/api/v1/uploads", json={"filename": "long_observations.csv", "size_bytes": len(payload)}
    )
    upload_id = create.json()["upload_id"]
    await client.put(f"/api/v1/uploads/{upload_id}/parts/1", content=payload)
    await client.post(f"/api/v1/uploads/{upload_id}/complete")
    abort = await client.post(f"/api/v1/uploads/{upload_id}/abort")
    assert abort.status_code == 409


async def test_unknown_upload_returns_the_error_envelope(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/uploads/upl_" + "0" * 32)
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "not_found"
    assert body["request_id"] == response.headers["x-request-id"]


async def test_job_cancellation_is_requested(
    client: httpx.AsyncClient, testdata_path: Path
) -> None:
    payload = testdata_path("long_observations.csv").read_bytes()
    create = await client.post(
        "/api/v1/uploads", json={"filename": "long_observations.csv", "size_bytes": len(payload)}
    )
    upload_id = create.json()["upload_id"]
    await client.put(f"/api/v1/uploads/{upload_id}/parts/1", content=payload)
    done = await client.post(f"/api/v1/uploads/{upload_id}/complete")
    job_id = done.json()["job_id"]

    cancel = await client.post(f"/api/v1/jobs/{job_id}/cancel")
    assert cancel.status_code == 202
    assert cancel.json()["cancel_requested"] is True

    job = await client.get(f"/api/v1/jobs/{job_id}")
    assert job.json()["cancel_requested"] is True

    missing = await client.get("/api/v1/jobs/job_" + "0" * 32)
    assert missing.status_code == 404


async def test_complete_rejects_a_binary_file_named_csv(
    client: httpx.AsyncClient, testdata_path: Path
) -> None:
    payload = testdata_path("binary_disguised.csv").read_bytes()
    create = await client.post(
        "/api/v1/uploads", json={"filename": "binary_disguised.csv", "size_bytes": len(payload)}
    )
    upload_id = create.json()["upload_id"]
    await client.put(f"/api/v1/uploads/{upload_id}/parts/1", content=payload)
    complete = await client.post(f"/api/v1/uploads/{upload_id}/complete")
    assert complete.status_code == 422
    assert complete.json()["error"]["code"] == "validation_error"


async def test_path_traversal_in_the_filename_is_rejected(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/uploads",
        json={"filename": "../evil.csv", "size_bytes": 10},
    )
    assert response.status_code == 422


async def test_cors_preflight_allows_the_uploader_headers(client: httpx.AsyncClient) -> None:
    """The browser uploader sends Content-Range and Idempotency-Key; both must preflight."""
    response = await client.options(
        "/api/v1/uploads",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,content-range,x-request-id,idempotency-key",
        },
    )
    assert response.status_code == 200
    allowed = response.headers.get("access-control-allow-headers", "")
    for header in ("content-type", "content-range", "x-request-id", "idempotency-key"):
        assert header in allowed.lower()
