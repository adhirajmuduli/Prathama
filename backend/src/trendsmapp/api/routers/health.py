"""Liveness and readiness probes.

Liveness answers whether the process is running. Readiness additionally
verifies that the database and the object store are reachable, so an
orchestrator never routes traffic to a process that cannot serve it.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response, status

from trendsmapp.persistence.database import database_health
from trendsmapp.storage.base import ObjectStore

__all__ = ["router"]

router = APIRouter(prefix="/api/v1/health", tags=["health"])


@router.get("/live")
async def liveness() -> dict[str, str]:
    """Return the liveness state of the process."""
    return {"status": "ok", "service": "trendsmapp"}


@router.get("/ready")
async def readiness(request: Request, response: Response) -> dict[str, Any]:
    """Return the readiness state of the process and its dependencies."""
    engine = request.app.state.engine
    object_store = request.app.state.object_store
    database_ok = await database_health(engine)
    storage_ok = _storage_ready(object_store)
    ready = database_ok and storage_ok
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ready" if ready else "degraded",
        "components": {
            "database": "ok" if database_ok else "unavailable",
            "object_store": "ok" if storage_ok else "unavailable",
        },
    }


def _storage_ready(object_store: ObjectStore) -> bool:
    """Return whether the object store answers a reachability probe."""
    try:
        return object_store.ping()
    except Exception:  # noqa: BLE001 - a failing probe means "not ready"
        return False
