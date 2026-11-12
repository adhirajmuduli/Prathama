"""Model-run endpoints: create runs from ML tasks and read their results.

Route handlers only validate and delegate to :class:`ModelService`; all
scientific computation happens in the worker's ``train`` job. The stored
artifacts of a run are the authoritative metrics, predictions, and
explanations documents, streamed back here without recomputation.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, status
from sqlalchemy.ext.asyncio import AsyncSession

from trendsmapp.api.dependencies import (
    SettingsDependency,
    get_object_store,
    get_session,
)
from trendsmapp.contracts.common import ArtifactRef
from trendsmapp.contracts.models import CreateModelRunResponse, ModelRunResponse
from trendsmapp.contracts.tasks import MLTask
from trendsmapp.errors import NotFoundError
from trendsmapp.persistence.models import ArtifactRow
from trendsmapp.services.model_training import ModelService
from trendsmapp.storage.base import ObjectStore

__all__ = ["router"]

router = APIRouter(prefix="/api/v1/model-runs", tags=["models"])


def _service(
    session: Annotated[AsyncSession, Depends(get_session)],
    store: Annotated[ObjectStore, Depends(get_object_store)],
    settings: SettingsDependency,
) -> ModelService:
    """Build the model service for one request."""
    return ModelService(session=session, store=store, settings=settings)


ModelServiceDependency = Annotated[ModelService, Depends(_service)]


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


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=CreateModelRunResponse)
async def create_model_run(
    task: MLTask,
    service: ModelServiceDependency,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> CreateModelRunResponse:
    """Validate a task against a sealed dataset version and enqueue the training job.

    The task hash is the idempotency key of the run: reposting the same task on
    the same dataset version returns the existing run instead of enqueueing a
    duplicate job.
    """
    created = await service.create(task, idempotency_key=idempotency_key)
    return CreateModelRunResponse(**created)


@router.get("/{run_id}", response_model=ModelRunResponse)
async def get_model_run(
    run_id: str,
    service: ModelServiceDependency,
) -> ModelRunResponse:
    """Return one model run with its task, results, explanations, and artifacts."""
    row = await service.get_run(run_id)
    artifacts = [_artifact_response(item) for item in await service.list_artifacts(run_id)]
    results: dict[str, Any] | None = None
    explanations: dict[str, Any] | None = None
    if row.status == "succeeded":
        try:
            results = await service.artifact_document(run_id, "metrics")
        except NotFoundError:
            results = None
        try:
            explanations = await service.artifact_document(run_id, "explanations")
        except NotFoundError:
            explanations = None
    warnings: tuple[str, ...] = ()
    if results is not None:
        warnings = tuple(str(item) for item in results.get("warnings", []))
    return ModelRunResponse(
        run_id=row.id,
        dataset_version_id=row.dataset_version_id,
        job_id=row.job_id,
        status=row.status,
        task=MLTask.model_validate(row.recipe),
        task_hash=row.recipe_hash,
        created_at=row.created_at,
        finished_at=row.finished_at,
        results=results,
        explanations=explanations,
        artifacts=tuple(artifacts),
        warnings=warnings,
    )


@router.get("/{run_id}/metrics")
async def get_model_run_metrics(
    run_id: str,
    service: ModelServiceDependency,
) -> dict[str, Any]:
    """Return the stored metrics document of a model run."""
    return await service.artifact_document(run_id, "metrics")


@router.get("/{run_id}/folds")
async def get_model_run_folds(
    run_id: str,
    service: ModelServiceDependency,
) -> dict[str, Any]:
    """Return the per-fold metrics of every evaluated family of a model run."""
    document = await service.artifact_document(run_id, "metrics")
    return {"run_id": run_id, "folds": document.get("folds", [])}


@router.get("/{run_id}/predictions")
async def get_model_run_predictions(
    run_id: str,
    service: ModelServiceDependency,
) -> dict[str, Any]:
    """Return the held-out observed-versus-predicted table of a model run."""
    return await service.artifact_document(run_id, "predictions")


@router.get("/{run_id}/explanations")
async def get_model_run_explanations(
    run_id: str,
    service: ModelServiceDependency,
) -> dict[str, Any]:
    """Return the stored explanations document of a model run."""
    return await service.artifact_document(run_id, "explanations")


@router.get("/{run_id}/artifacts")
async def list_model_run_artifacts(
    run_id: str,
    service: ModelServiceDependency,
) -> dict[str, Any]:
    """Return every artifact a model run produced."""
    rows = await service.list_artifacts(run_id)
    return {
        "run_id": run_id,
        "items": [_artifact_response(row).model_dump(mode="json") for row in rows],
    }
