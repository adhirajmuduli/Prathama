import json

import pytest


@pytest.mark.asyncio
async def test_health_openapi_upload_and_scientific_heatmaps(client):
    health = await client.get("/api/health")
    assert health.json() == {"status": "ok"}
    openapi = await client.get("/openapi.json")
    assert openapi.status_code == 200
    assert "/api/visualization/frames" not in openapi.json()["paths"]
    configuration = (await client.get("/api/config")).json()
    assert configuration["client_gpu_criteria"]["required_api"] == "webgl2"
    assert configuration["client_gpu_criteria"]["gpu_absent_fallbacks"] == [
        "scientific_idw", "scientific_kde"
    ]
    pipelines = {item["id"]: item for item in configuration["animation_pipelines"]}
    assert pipelines["scientific_idw"]["requires_client_gpu"] is False
    assert pipelines["scientific_kde"]["requires_client_gpu"] is False
    assert set(pipelines) == {"scientific_idw", "scientific_kde"}
    missing = await client.get("/removed-legacy-route")
    assert missing.status_code == 404
    assert missing.json() == {"error": "Not Found"}

    content = (
        b"latitude,longitude,timestamp,value,parameter\n"
        b"19.50,85.10,2024-01-01,1.0,chlorophyll\n"
        b"19.55,85.15,2024-01-01,2.0,chlorophyll\n"
        b"19.60,85.20,2024-01-01,3.0,chlorophyll\n"
    )
    uploaded = await client.post("/upload", files={"file": ("observations.csv", content, "text/csv")})
    assert uploaded.status_code == 200
    payload = uploaded.json()
    assert payload["total_records"] == 3
    assert payload["timestamp_columns"] == ["2024-01-01T00:00:00Z"]

    for method in ("idw", "kde"):
        heatmap = await client.post("/generate-heatmap", json={
            "data": payload["data"],
            "timestamp_columns": payload["timestamp_columns"],
            "global_min": payload["global_min"],
            "global_max": payload["global_max"],
            "method": method,
            "idw_power": 2.0,
            "kde_bandwidth_km": 2.0,
            "colormap": "viridis",
        })
        assert heatmap.status_code == 200
        assert heatmap.json()["method"] == method
        assert len(heatmap.json()["bounds"]) == 2
        assert set(heatmap.json()["images"]) == {"2024-01-01T00:00:00Z"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "content", "message"),
    [
        ("missing.csv", b"timestamp,value\n2024-01-01,1\n", "latitude and longitude"),
        ("timestamp.csv", b"latitude,longitude,timestamp,value\n19.5,85.1,not-a-date,1\n", "invalid timestamp"),
        ("value.csv", b"latitude,longitude,timestamp,value\n19.5,85.1,2024-01-01,Infinity\n", "non-numeric or non-finite"),
        ("corrupt.xlsx", b"not-an-excel-archive", "corrupted or cannot be parsed"),
    ],
)
async def test_upload_validation_errors_are_clear(client, name, content, message):
    response = await client.post("/upload", files={"file": (name, content)})
    assert response.status_code == 400
    assert message in response.json()["error"]


@pytest.mark.asyncio
async def test_rejects_invalid_boundary(client):
    response = await client.post(
        "/upload-boundary", files={"file": ("boundary.geojson", b"not-json", "application/geo+json")}
    )
    assert response.status_code == 400
    assert "error" in response.json()


@pytest.mark.asyncio
async def test_data_entry_round_trip_and_delete(client):
    measurement = {
        "latitude": 19.5,
        "longitude": 85.1,
        "parameter": "chlorophyll",
        "timestamp": "2024-01-01",
        "value": 2.5,
    }
    saved = await client.post("/api/table", json=[measurement])
    assert saved.status_code == 200
    rows = (await client.get("/api/table")).json()
    assert rows[0]["chlorophyll_2024-01-01"] == 2.5

    deleted = await client.request("DELETE", "/api/measurement", json=measurement)
    assert deleted.status_code == 200
    assert (await client.get("/api/table")).json() == []

@pytest.mark.asyncio
async def test_table_delete_station_removes_coordinate_row(client):
    measurement = {
        "latitude": 19.5,
        "longitude": 85.1,
        "timestamp": "2024-01-01",
        "value": 2.1,
        "parameter": "chlorophyll",
    }
    assert (await client.post("/api/table", json=[measurement])).status_code == 200
    deleted = await client.post(
        "/api/table/delete-station", json={"latitude": 19.5, "longitude": 85.1}
    )
    assert deleted.status_code == 200
    assert (await client.get("/api/table")).json() == []


@pytest.mark.asyncio
async def test_boundary_accepts_polygon_geojson(client):
    boundary = json.dumps({
        "type": "Polygon",
        "coordinates": [[[85.0, 19.4], [85.3, 19.4], [85.3, 19.7], [85.0, 19.7], [85.0, 19.4]]],
    }).encode()
    response = await client.post(
        "/upload-boundary", files={"file": ("boundary.geojson", boundary, "application/geo+json")}
    )
    assert response.status_code == 200
    assert response.json()["path"].startswith("/static/data/uploads/")
