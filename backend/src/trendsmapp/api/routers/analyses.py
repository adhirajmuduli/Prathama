"""Analysis endpoints: create runs from recipes and read their results."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from trendsmapp.api.dependencies import (
    SettingsDependency,
    get_artifact_repository,
    get_object_store,
    get_session,
)
from trendsmapp.contracts.common import ArtifactRef
from trendsmapp.contracts.recipes import Recipe
from trendsmapp.persistence.models import ArtifactRow, RunRow
from trendsmapp.persistence.repositories.artifacts import ArtifactRepository
from trendsmapp.services.analyses import AnalysisService
from trendsmapp.storage.base import ObjectStore

__all__ = ["router"]

router = APIRouter(prefix="/api/v1/analyses", tags=["analyses"])


def _service(
    session: Annotated[AsyncSession, Depends(get_session)],
    store: Annotated[ObjectStore, Depends(get_object_store)],
    settings: SettingsDependency,
) -> AnalysisService:
    """Build the analysis service for one request."""
    return AnalysisService(session=session, store=store, settings=settings)


AnalysisServiceDependency = Annotated[AnalysisService, Depends(_service)]


@router.post("/{run_id}/animations", status_code=status.HTTP_202_ACCEPTED)
async def create_animation(
    run_id: str,
    request: AnimationRequest,
    service: AnalysisServiceDependency,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, str]:
    """Enqueue an animation job over the stored rasters of a run."""
    job = await service.create_animation(run_id, request, idempotency_key)
    return job


class AnimationRequest(BaseModel):
    """The body of ``POST /api/v1/analyses/{run_id}/animations``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    parameter_id: str | None = None
    method: str | None = None
    palette: str = "viridis"
    fps: int = Field(default=2, ge=1, le=30)


def _run_response(row: RunRow) -> dict[str, Any]:
    """Serialize one run row."""
    return {
        "run_id": row.id,
        "dataset_version_id": row.dataset_version_id,
        "job_id": row.job_id,
        "recipe_hash": row.recipe_hash,
        "recipe": row.recipe,
        "dataset_sha256": row.dataset_sha256,
        "boundary_sha256": row.boundary_sha256,
        "seed": row.seed,
        "application_version": row.application_version,
        "schema_version": row.schema_version,
        "status": row.status,
        "created_at": row.created_at.isoformat(),
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
    }


def _artifact_response(row: ArtifactRow) -> ArtifactRef:
    """Serialize one artifact row."""
    return ArtifactRef(
        artifact_id=row.id,
        kind=row.kind,
        sha256=row.sha256,
        size_bytes=row.size_bytes,
        content_type=row.content_type,
        schema_version=row.schema_version,
        created_at=row.created_at,
        media_type_detail=dict(row.details or {}),
    )


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create_analysis(
    recipe: Recipe,
    service: AnalysisServiceDependency,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, str]:
    """Validate a recipe and enqueue the analysis job."""
    created = await service.create(recipe, idempotency_key=idempotency_key)
    return created.as_dict()


@router.get("/{run_id}")
async def get_analysis(
    run_id: str,
    service: AnalysisServiceDependency,
) -> dict[str, Any]:
    """Return one analysis run."""
    return _run_response(await service.get_run(run_id))


@router.get("/{run_id}/artifacts")
async def list_analysis_artifacts(
    run_id: str,
    service: AnalysisServiceDependency,
) -> dict[str, Any]:
    """Return every artifact a run produced."""
    rows = await service.list_artifacts(run_id)
    return {
        "run_id": run_id,
        "items": [_artifact_response(row).model_dump(mode="json") for row in rows],
    }


@router.get("/{run_id}/results")
async def get_analysis_results(
    run_id: str,
    service: AnalysisServiceDependency,
    repository: Annotated[ArtifactRepository, Depends(get_artifact_repository)],
    store: Annotated[ObjectStore, Depends(get_object_store)],
) -> dict[str, Any]:
    """Return the stored analysis-results document of a run."""
    artifact = await service.report_artifact(run_id, "metrics")
    payload = store.get_bytes(artifact.storage_key)
    import json

    document: dict[str, Any] = json.loads(payload.decode("utf-8"))
    return document
