import httpx
import pytest
import pytest_asyncio
import os

from db import Base, engine


@pytest.fixture(autouse=True)
def isolate_auth_configuration(monkeypatch):
    """Guarantee token auth is disabled unless a test opts in explicitly."""
    monkeypatch.setenv("TRENDSMAPP_AUTH_TOKEN", "")


@pytest_asyncio.fixture(autouse=True)
async def clean_database():
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)


@pytest.fixture
def auth_token(monkeypatch):
    """Enable shared-token authentication for tests that explicitly request it."""
    monkeypatch.setenv("TRENDSMAPP_AUTH_TOKEN", "unit-test-secret")
    return "unit-test-secret"


@pytest_asyncio.fixture
async def client():
    # Import app inside the fixture so environment variables are already set
    from app import app
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as test_client:
        yield test_client
