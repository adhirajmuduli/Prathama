from __future__ import annotations

import ssl
from dataclasses import replace

import httpx
import pandas as pd
import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

import app as app_module
import utils.animation_generator as animation_generator_module
from config import settings
from db import _database_configuration, _postgres_ssl_argument
from routes.data_api import _pivot_measurements
from utils.security import SecurityHeadersMiddleware


def test_ssl_require_is_encrypted_but_unauthenticated(monkeypatch):
    argument = _postgres_ssl_argument("require", None)
    assert isinstance(argument, ssl.SSLContext)
    assert argument.check_hostname is False
    assert argument.verify_mode == ssl.CERT_NONE


def test_ssl_verify_ca_validates_certificate_not_hostname():
    argument = _postgres_ssl_argument("verify-ca", None)
    assert isinstance(argument, ssl.SSLContext)
    assert argument.check_hostname is False
    assert argument.verify_mode == ssl.CERT_REQUIRED


def test_ssl_verify_full_also_checks_hostname():
    argument = _postgres_ssl_argument("verify-full", None)
    assert isinstance(argument, ssl.SSLContext)
    assert argument.check_hostname is True
    assert argument.verify_mode == ssl.CERT_REQUIRED


def test_ssl_disable_and_default_modes():
    assert _postgres_ssl_argument("disable", None) is False
    for mode in ("", "allow", "prefer"):
        assert _postgres_ssl_argument(mode, None) is None
    with pytest.raises(RuntimeError):
        _postgres_ssl_argument("nonsense", None)


def test_database_url_ssl_parameters_are_translated(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgres://u:p@h:5432/db?sslmode=verify-full&channel_binding=require",
    )
    url, connect_args = _database_configuration()
    assert url.startswith("postgresql+asyncpg://u:p@h:5432/db")
    assert "sslmode" not in url and "channel_binding" not in url
    context = connect_args["ssl"]
    assert isinstance(context, ssl.SSLContext)
    assert context.check_hostname is True


def test_unreadable_root_certificate_fails_fast(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "DATABASE_URL",
        f"postgres://u:p@h:5432/db?sslmode=verify-ca&sslrootcert={tmp_path / 'missing-ca.pem'}",
    )
    with pytest.raises(OSError):
        _database_configuration()


def test_database_url_without_sslmode_keeps_driver_default(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@h:5432/db")
    url, connect_args = _database_configuration()
    assert url.startswith("postgresql+asyncpg://")
    assert connect_args == {}


def test_missing_database_url_still_resolves_to_sqlite(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    url, connect_args = _database_configuration()
    assert url.startswith("sqlite+aiosqlite:///")
    assert connect_args == {}


def test_allocate_transition_frames_is_gap_proportional_and_exact():
    allocation = animation_generator_module.allocate_transition_frames([86_400.0, 864_000.0], 22)
    assert allocation == [2, 20]

    minimum_one = animation_generator_module.allocate_transition_frames([1.0, 1000.0], 3)
    assert minimum_one == [1, 2]

    deficit = animation_generator_module.allocate_transition_frames([1.0, 1.0, 1000.0], 4)
    assert sum(deficit) == 4
    assert min(deficit) >= 1
    assert deficit[-1] == max(deficit)

    uniform = animation_generator_module.allocate_transition_frames([10.0, 10.0, 10.0], 30)
    assert uniform == [10, 10, 10]

    repeat = animation_generator_module.allocate_transition_frames([1.0, 1.0, 1000.0], 4)
    assert repeat == deficit


@pytest.mark.asyncio
async def test_animation_frame_budget_is_enforced_before_rendering(client):
    content = (
        b"latitude,longitude,timestamp,value\n"
        b"19.5,85.1,2024-01-01,1\n"
        b"19.6,85.2,2024-02-01,2\n"
        b"19.7,85.3,2024-03-01,3\n"
    )
    uploaded = await client.post("/upload", files={"file": ("rows.csv", content, "text/csv")})
    payload = uploaded.json()
    monkeypatch_frames = 3
    original = animation_generator_module.MAX_VIDEO_FRAMES
    animation_generator_module.MAX_VIDEO_FRAMES = monkeypatch_frames
    try:
        response = await client.post("/api/animate", json={
            "parameter": "",
            "start_date": payload["timestamp_columns"][0],
            "end_date": payload["timestamp_columns"][-1],
            "fps": 2,
            "frames_per_transition": 2,
            "filename": payload["filename"],
            "method": "idw",
            "temporal_method": "linear_surface_interpolation",
        })
    finally:
        animation_generator_module.MAX_VIDEO_FRAMES = original
    assert response.status_code == 400
    assert f"{monkeypatch_frames}-frame prototype limit" in response.json()["error"]


@pytest.mark.asyncio
async def test_heatmap_honors_configured_surface_resolution(client, monkeypatch):
    monkeypatch.setattr(app_module, "settings", replace(settings, surface_resolution=60))
    content = (
        b"latitude,longitude,timestamp,value\n"
        b"19.5,85.1,2024-01-01,1\n"
        b"19.6,85.2,2024-01-01,2\n"
    )
    uploaded = await client.post("/upload", files={"file": ("rows.csv", content, "text/csv")})
    payload = uploaded.json()
    response = await client.post("/generate-heatmap", json={
        "data": payload["data"],
        "timestamp_columns": payload["timestamp_columns"],
        "global_min": payload["global_min"],
        "global_max": payload["global_max"],
        "method": "idw",
        "colormap": "viridis",
    })
    assert response.status_code == 200
    assert response.json()["images"]


def test_pivot_measurements_rejects_conflicting_duplicates():
    frame = pd.DataFrame([
        {"station_id": 1, "latitude": 19.5, "longitude": 85.1, "param_date": "chla_2024-01-01", "value": 1.0},
        {"station_id": 1, "latitude": 19.5, "longitude": 85.1, "param_date": "chla_2024-01-01", "value": 9.0},
    ])
    with pytest.raises(ValueError) as excinfo:
        _pivot_measurements(frame)
    assert "uniqueness contract" in str(excinfo.value)


def test_pivot_measurements_pivots_unique_rows():
    frame = pd.DataFrame([
        {"station_id": 1, "latitude": 19.5, "longitude": 85.1, "param_date": "chla_2024-01-01", "value": 1.0},
        {"station_id": 1, "latitude": 19.5, "longitude": 85.1, "param_date": "chla_2024-02-01", "value": 2.0},
        {"station_id": 2, "latitude": 19.6, "longitude": 85.2, "param_date": "chla_2024-01-01", "value": 3.0},
    ])
    pivoted = _pivot_measurements(frame)
    assert list(pivoted.columns) == ["station_id", "latitude", "longitude", "chla_2024-01-01", "chla_2024-02-01"]
    assert pivoted.iloc[0]["chla_2024-01-01"] == 1.0


@pytest.mark.asyncio
async def test_security_headers_wrap_responses(client):
    response = await client.get("/api/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    policy = response.headers["content-security-policy"]
    assert policy.startswith("default-src 'self'")
    assert "frame-ancestors 'none'" in policy
    assert "worker-src 'self' blob:" in policy


@pytest.mark.asyncio
async def test_health_payload_discloses_no_version(client):
    body = (await client.get("/api/health")).json()
    assert body == {"status": "ok"}


@pytest.mark.asyncio
async def test_legend_supports_horizontal_orientation(client):
    horizontal = await client.get("/legend/x.png?min=0&max=1&colormap=viridis&orientation=horizontal")
    assert horizontal.status_code == 200
    assert horizontal.content.startswith(b"\x89PNG")

    invalid = await client.get("/legend/x.png?min=0&max=1&colormap=viridis&orientation=diagonal")
    assert invalid.status_code == 400


@pytest.mark.asyncio
async def test_security_headers_middleware_does_not_duplicate_existing_headers():
    async def echo(request):
        return JSONResponse({"ok": True}, headers={"X-Content-Type-Options": "nosniff"})

    application = Starlette(routes=[Route("/", echo)])
    application.add_middleware(SecurityHeadersMiddleware)

    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as probe:
        response = await probe.get("/")
        values = response.headers.get_list("x-content-type-options")
        assert values == ["nosniff"]
        assert response.headers["x-frame-options"] == "DENY"
