from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

import app as app_module
from utils.storage import purge_expired_files


@pytest.mark.asyncio
async def test_demo_loads_without_writing_upload_files(client):
    before = {path.name for path in app_module.UPLOAD_DIR.iterdir()}
    response = await client.get("/api/demo")
    assert response.status_code == 200
    payload = response.json()
    assert payload["filename"].startswith("__demo__")
    after = {path.name for path in app_module.UPLOAD_DIR.iterdir()}
    assert after == before


@pytest.mark.asyncio
async def test_demo_session_marker_supports_animation(client):
    demo = await client.get("/api/demo")
    payload = demo.json()
    timestamps = sorted(payload["timestamp_columns"])
    assert len(timestamps) >= 2
    response = await client.post("/api/animate", json={
        "parameter": "",
        "start_date": timestamps[0],
        "end_date": timestamps[1],
        "fps": 2,
        "frames_per_transition": 1,
        "filename": payload["filename"],
        "colormap": "viridis",
        "method": "idw",
        "temporal_method": "linear_surface_interpolation",
    })
    assert response.status_code == 200
    assert response.headers["content-type"] == "video/mp4"
    assert b"ftyp" in response.content[:64]


@pytest.mark.asyncio
async def test_new_upload_replaces_previous_session_file(client):
    first_content = (
        b"latitude,longitude,timestamp,value\n"
        b"19.5,85.1,2024-01-01,1\n"
    )
    second_content = (
        b"latitude,longitude,timestamp,value\n"
        b"19.5,85.1,2024-02-01,2\n"
        b"19.6,85.2,2024-02-01,3\n"
    )
    first = await client.post(
        "/upload", files={"file": ("first.csv", first_content, "text/csv")}
    )
    second = await client.post(
        "/upload", files={"file": ("second.csv", second_content, "text/csv")}
    )
    assert first.status_code == 200 and second.status_code == 200
    first_name = first.json()["filename"]
    second_name = second.json()["filename"]
    assert first_name != second_name
    assert not (app_module.UPLOAD_DIR / Path(first_name).name).exists()
    assert (app_module.UPLOAD_DIR / Path(second_name).name).is_file()

    cleanup = await client.post("/upload", files={"file": ("first.csv", first_content, "text/csv")})
    assert cleanup.status_code == 200
    assert not (app_module.UPLOAD_DIR / Path(second_name).name).exists()


@pytest.mark.asyncio
async def test_boundary_upload_replaces_previous_session_boundary(client):
    import json

    polygon_a = {
        "type": "Polygon",
        "coordinates": [[[85.0, 19.4], [85.2, 19.4], [85.2, 19.6], [85.0, 19.6], [85.0, 19.4]]],
    }
    polygon_b = {
        "type": "Polygon",
        "coordinates": [[[85.05, 19.45], [85.25, 19.45], [85.25, 19.65], [85.05, 19.65], [85.05, 19.45]]],
    }
    first = await client.post(
        "/upload-boundary",
        files={"file": ("a.geojson", json.dumps(polygon_a).encode(), "application/geo+json")},
    )
    second = await client.post(
        "/upload-boundary",
        files={"file": ("b.geojson", json.dumps(polygon_b).encode(), "application/geo+json")},
    )
    assert first.status_code == 200 and second.status_code == 200
    first_name = Path(first.json()["path"]).name
    second_name = Path(second.json()["path"]).name
    assert not (app_module.BOUNDARY_UPLOAD_DIR / first_name).exists()
    assert (app_module.BOUNDARY_UPLOAD_DIR / second_name).is_file()


def _seed_rows(parameter: str = "chlorophyll"):
    return [
        {
            "latitude": latitude,
            "longitude": longitude,
            "parameter": parameter,
            "timestamp": timestamp,
            "value": value,
        }
        for timestamp, value in [("2024-01-01", 1.0), ("2024-02-01", 2.0)]
        for latitude, longitude in [(19.5, 85.1), (19.6, 85.2)]
    ]


@pytest.mark.asyncio
async def test_export_dataset_bridges_database_to_science_plane(client):
    saved = await client.post("/api/table", json=_seed_rows())
    assert saved.status_code == 200

    export = await client.post("/api/export-dataset")
    assert export.status_code == 200
    payload = export.json()
    assert payload["total_records"] == 4
    assert payload["original_filename"] == "database_export.csv"
    assert payload["filename"].endswith("_database_export.csv")
    assert set(payload["data"][0]) >= {"latitude", "longitude", "timestamp", "value", "parameter"}

    heatmap = await client.post("/generate-heatmap", json={
        "data": payload["data"],
        "parameter": "chlorophyll",
        "timestamp_columns": payload["timestamp_columns"][:1],
        "global_min": payload["global_min"],
        "global_max": payload["global_max"],
        "method": "idw",
        "colormap": "viridis",
    })
    assert heatmap.status_code == 200
    assert heatmap.json()["parameter"] == "chlorophyll"

    animation_ready = await client.post("/api/animate", json={
        "parameter": "chlorophyll",
        "start_date": "2024-01-01",
        "end_date": "2024-02-01",
        "fps": 2,
        "frames_per_transition": 1,
        "filename": payload["filename"],
        "colormap": "viridis",
        "method": "kde",
        "temporal_method": "linear_surface_interpolation",
    })
    assert animation_ready.status_code == 200
    assert animation_ready.headers["content-type"] == "video/mp4"


@pytest.mark.asyncio
async def test_export_dataset_rejects_empty_database(client):
    response = await client.post("/api/export-dataset")
    assert response.status_code == 400
    assert "no measurements" in response.json()["error"]


@pytest.mark.asyncio
async def test_delete_series_single_timestamp_keeps_other_dates(client):
    await client.post("/api/table", json=_seed_rows())
    deleted = await client.post(
        "/api/table/delete-series", json={"parameter": "chlorophyll", "timestamp": "2024-01-01"}
    )
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] == 2
    rows = (await client.get("/api/table")).json()
    assert rows and "chlorophyll_2024-01-01" not in rows[0]
    assert rows[0]["chlorophyll_2024-02-01"] is not None


@pytest.mark.asyncio
async def test_delete_series_whole_parameter_removes_parameter_row(client):
    await client.post("/api/table", json=_seed_rows())
    deleted = await client.post("/api/table/delete-series", json={"parameter": "chlorophyll"})
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] == 4
    assert (await client.get("/api/table")).json() == []
    parameters = (await client.get("/api/parameters")).json()
    assert "chlorophyll" not in parameters


@pytest.mark.asyncio
async def test_delete_series_unknown_target_returns_404(client):
    response = await client.post("/api/table/delete-series", json={"parameter": "ghost"})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_rename_parameter_persists_to_measurements(client):
    await client.post("/api/table", json=_seed_rows())
    renamed = await client.post(
        "/api/table/rename-parameter", json={"old_name": "chlorophyll", "new_name": "chla"}
    )
    assert renamed.status_code == 200
    rows = (await client.get("/api/table")).json()
    assert rows and rows[0]["chla_2024-01-01"] == 1.0
    assert "chlorophyll_2024-01-01" not in rows[0]


@pytest.mark.asyncio
async def test_rename_parameter_conflict_is_409(client):
    await client.post("/api/table", json=_seed_rows())
    await client.post("/api/table", json=_seed_rows("temperature"))
    conflict = await client.post(
        "/api/table/rename-parameter", json={"old_name": "chlorophyll", "new_name": "temperature"}
    )
    assert conflict.status_code == 409


@pytest.mark.asyncio
async def test_rename_parameter_missing_is_404(client):
    response = await client.post(
        "/api/table/rename-parameter", json={"old_name": "ghost", "new_name": "other"}
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_rename_timestamp_moves_series_to_new_date(client):
    await client.post("/api/table", json=_seed_rows())
    response = await client.post(
        "/api/table/rename-timestamp",
        json={"parameter": "chlorophyll", "old_timestamp": "2024-01-01", "new_timestamp": "2024-03-15"},
    )
    assert response.status_code == 200
    assert response.json()["moved"] == 2
    rows = (await client.get("/api/table")).json()
    assert rows and rows[0]["chlorophyll_2024-03-15"] == 1.0
    assert "chlorophyll_2024-01-01" not in rows[0]
    assert rows[0]["chlorophyll_2024-02-01"] == 2.0


@pytest.mark.asyncio
async def test_rename_timestamp_without_parameter_moves_every_group(client):
    await client.post("/api/table", json=_seed_rows())
    await client.post("/api/table", json=_seed_rows("temperature"))
    response = await client.post(
        "/api/table/rename-timestamp",
        json={"old_timestamp": "2024-02-01", "new_timestamp": "2024-04-01"},
    )
    assert response.status_code == 200
    assert response.json()["moved"] == 4
    rows = (await client.get("/api/table")).json()
    assert rows[0]["chlorophyll_2024-04-01"] == 2.0
    assert rows[0]["temperature_2024-04-01"] == 2.0


@pytest.mark.asyncio
async def test_rename_timestamp_conflicting_target_date_is_409(client):
    await client.post("/api/table", json=_seed_rows())
    conflict = await client.post(
        "/api/table/rename-timestamp",
        json={"parameter": "chlorophyll", "old_timestamp": "2024-01-01", "new_timestamp": "2024-02-01"},
    )
    assert conflict.status_code == 409
    assert "already exists" in conflict.json()["error"]


@pytest.mark.asyncio
async def test_rename_timestamp_validation_and_allow_missing(client):
    missing_fields = await client.post("/api/table/rename-timestamp", json={"old_timestamp": "2024-01-01"})
    assert missing_fields.status_code == 400

    identical = await client.post(
        "/api/table/rename-timestamp", json={"old_timestamp": "2024-01-01", "new_timestamp": "2024-01-01"}
    )
    assert identical.status_code == 400

    malformed = await client.post(
        "/api/table/rename-timestamp", json={"old_timestamp": "not-a-date", "new_timestamp": "2024-02-02"}
    )
    assert malformed.status_code == 400

    unsaved = await client.post(
        "/api/table/rename-timestamp",
        json={
            "parameter": "ghost",
            "old_timestamp": "1999-01-01",
            "new_timestamp": "1999-01-02",
            "allow_missing": True,
        },
    )
    assert unsaved.status_code == 200
    assert unsaved.json()["moved"] == 0

    strict = await client.post(
        "/api/table/rename-timestamp",
        json={"parameter": "ghost", "old_timestamp": "1999-01-01", "new_timestamp": "1999-01-02"},
    )
    assert strict.status_code == 404


@pytest.mark.asyncio
async def test_heatmap_rejects_mixed_parameters(client):
    mixed = [
        {"latitude": 19.5, "longitude": 85.1, "timestamp": "2024-01-01T00:00:00Z", "value": 1.0, "parameter": "chlorophyll"},
        {"latitude": 19.6, "longitude": 85.2, "timestamp": "2024-01-01T00:00:00Z", "value": 5.0, "parameter": "iron"},
    ]
    rejected = await client.post("/generate-heatmap", json={"data": mixed})
    assert rejected.status_code == 400
    assert "multiple parameters" in rejected.json()["error"]

    unknown = await client.post("/generate-heatmap", json={"data": mixed, "parameter": "nickel"})
    assert unknown.status_code == 400
    assert "Unknown parameter 'nickel'" in unknown.json()["error"]

    selected = await client.post("/generate-heatmap", json={"data": mixed, "parameter": "iron"})
    assert selected.status_code == 200
    body = selected.json()
    assert body["parameter"] == "iron"
    assert set(body["images"]) == {"2024-01-01T00:00:00Z"}


def test_purge_expired_files_respects_ttl(tmp_path):
    old_artifact = tmp_path / (f"{'a' * 32}_observations.csv")
    fresh_artifact = tmp_path / (f"{'b' * 32}_rows.csv")
    foreign_file = tmp_path / "Testfile.xlsx"
    old_artifact.write_bytes(b"x")
    fresh_artifact.write_bytes(b"y")
    foreign_file.write_bytes(b"tracked-content")
    stale_time = time.time() - 10 * 3600
    os.utime(old_artifact, (stale_time, stale_time))
    os.utime(foreign_file, (stale_time, stale_time))

    removed_disabled = purge_expired_files((tmp_path,), ttl_hours=0)
    assert removed_disabled == 0
    assert old_artifact.exists() and fresh_artifact.exists() and foreign_file.exists()

    removed = purge_expired_files((tmp_path,), ttl_hours=1)
    assert removed == 1
    assert not old_artifact.exists()
    assert fresh_artifact.exists()
    assert foreign_file.exists()
