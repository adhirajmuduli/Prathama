import json

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["idw", "kde"])
async def test_session_upload_boundary_and_animation_download(client, method):
    rows = ["latitude,longitude,timestamp,value,parameter"]
    for timestamp, offset in [("2024-01-01", 0), ("2024-02-01", 1)]:
        for latitude, longitude, value in [
            (19.45, 85.05, 1), (19.45, 85.25, 2), (19.65, 85.05, 3), (19.65, 85.25, 4)
        ]:
            rows.append(f"{latitude},{longitude},{timestamp},{value + offset},chlorophyll")
    boundary = json.dumps({
        "type": "Polygon",
        "coordinates": [[[85.0, 19.4], [85.3, 19.4], [85.3, 19.7], [85.0, 19.7], [85.0, 19.4]]],
    }).encode()

    uploaded = await client.post(
        "/upload", files={"file": ("animation.csv", "\n".join(rows).encode(), "text/csv")}
    )
    assert uploaded.status_code == 200
    boundary_response = await client.post(
        "/upload-boundary", files={"file": ("boundary.geojson", boundary, "application/geo+json")}
    )
    assert boundary_response.status_code == 200

    response = await client.post("/api/animate", json={
        "parameter": "chlorophyll",
        "start_date": "2024-01-01",
        "end_date": "2024-02-01",
        "fps": 2,
        "frames_per_transition": 1,
        "filename": uploaded.json()["filename"],
        "boundary_path": boundary_response.json()["path"],
        "colormap": "viridis",
        "method": method,
        "temporal_method": "linear_surface_interpolation",
    })
    assert response.status_code == 200
    assert response.headers["content-type"] == "video/mp4"
    assert response.headers["x-trendsmapp-spatial-method"] == method
    assert response.headers["x-trendsmapp-temporal-method"] == "linear_surface_interpolation"
    assert response.headers["x-trendsmapp-execution"] == "server_cpu"
    assert b"ftyp" in response.content[:64]


@pytest.mark.asyncio
async def test_animation_rejects_filename_outside_session(client):
    response = await client.post("/api/animate", json={
        "parameter": "chlorophyll",
        "start_date": "2024-01-01",
        "end_date": "2024-02-01",
        "fps": 2,
        "frames_per_transition": 1,
        "filename": "another-session.csv",
    })
    assert response.status_code == 400
    assert "not available in this session" in response.json()["error"]


@pytest.mark.asyncio
async def test_animation_rejects_non_scientific_server_method(client):
    response = await client.post("/api/animate", json={
        "start_date": "2024-01-01",
        "end_date": "2024-02-01",
        "fps": 2,
        "frames_per_transition": 1,
        "filename": "not-used.csv",
        "method": "gpu",
    })
    assert response.status_code == 400
    assert "must be 'idw' or 'kde'" in response.json()["error"]
