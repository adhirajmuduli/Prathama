"""Dataset, probe, preview, report, provenance, and artifact endpoints."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from trendsmapp.api.dependencies import (
    SettingsDependency,
    get_artifact_repository,
    get_object_store,
    get_session,
)
from trendsmapp.contracts.common import ArtifactRef
from trendsmapp.contracts.datasets import (
    CreateDatasetRequest,
    CreateDatasetResponse,
    DatasetListResponse,
    DatasetResponse,
    DatasetVersionListResponse,
    DatasetVersionResponse,
    PreviewResponse,
    ProbeResponse,
    ProvenanceListResponse,
    ReportKind,
)
from trendsmapp.persistence.repositories.artifacts import ArtifactRepository
from trendsmapp.services.datasets import DatasetService
from trendsmapp.storage.base import ObjectStore

__all__ = ["router"]

router = APIRouter(prefix="/api/v1", tags=["datasets"])


def _service(
    session: Annotated[AsyncSession, Depends(get_session)],
    store: Annotated[ObjectStore, Depends(get_object_store)],
    settings: SettingsDependency,
) -> DatasetService:
    """Build the dataset service for one request."""
    return DatasetService(session=session, store=store, settings=settings)


DatasetServiceDependency = Annotated[DatasetService, Depends(_service)]


@router.get("/datasets", response_model=DatasetListResponse)
async def list_datasets(
    service: DatasetServiceDependency,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DatasetListResponse:
    """Return a page of datasets, most recently updated first."""
    return await service.list_datasets(limit=limit, offset=offset)


@router.post("/uploads/{upload_id}/probe", response_model=ProbeResponse)
async def probe_upload(
    upload_id: str,
    service: DatasetServiceDependency,
) -> ProbeResponse:
    """Describe the first rows of a completed upload and propose a mapping."""
    return await service.probe(upload_id)


@router.post(
    "/datasets", response_model=CreateDatasetResponse, status_code=status.HTTP_202_ACCEPTED
)
async def create_dataset(
    request: CreateDatasetRequest,
    service: DatasetServiceDependency,
) -> CreateDatasetResponse:
    """Create a dataset version from an upload and a confirmed mapping."""
    return await service.create(request)


@router.get("/datasets/{dataset_id}", response_model=DatasetResponse)
async def get_dataset(
    dataset_id: str,
    service: DatasetServiceDependency,
) -> DatasetResponse:
    """Return one dataset."""
    return await service.get_dataset(dataset_id)


@router.get("/datasets/{dataset_id}/versions", response_model=DatasetVersionListResponse)
async def list_versions(
    dataset_id: str,
    service: DatasetServiceDependency,
) -> DatasetVersionListResponse:
    """Return every version of a dataset, oldest first."""
    return await service.list_versions(dataset_id)


@router.get("/dataset-versions/{version_id}", response_model=DatasetVersionResponse)
async def get_version(
    version_id: str,
    service: DatasetServiceDependency,
) -> DatasetVersionResponse:
    """Return one dataset version with its artifacts."""
    return await service.get_version(version_id)


@router.get("/dataset-versions/{version_id}/preview", response_model=PreviewResponse)
async def preview_version(
    version_id: str,
    service: DatasetServiceDependency,
    limit: Annotated[int, Query(ge=1, le=5000)] = 100,
) -> PreviewResponse:
    """Return the first rows of a normalized dataset version."""
    return await service.preview(version_id, limit=limit)


@router.get("/dataset-versions/{version_id}/reports/{kind}")
async def get_report(
    version_id: str,
    kind: ReportKind,
    service: DatasetServiceDependency,
) -> dict[str, Any]:
    """Return one stored JSON report of a dataset version."""
    return await service.report(version_id, kind)


@router.get("/dataset-versions/{version_id}/provenance", response_model=ProvenanceListResponse)
async def get_provenance(
    version_id: str,
    service: DatasetServiceDependency,
) -> ProvenanceListResponse:
    """Return the provenance events of a dataset version."""
    return await service.provenance(version_id)


@router.get("/artifacts/{artifact_id}", response_model=ArtifactRef)
async def get_artifact(
    artifact_id: str,
    service: DatasetServiceDependency,
) -> ArtifactRef:
    """Return one artifact reference."""
    return await service.artifact_ref(artifact_id)


@router.get("/artifacts/{artifact_id}/content")
async def download_artifact(
    artifact_id: str,
    request: Request,
    repository: Annotated[ArtifactRepository, Depends(get_artifact_repository)],
    store: Annotated[ObjectStore, Depends(get_object_store)],
) -> StreamingResponse:
    """Stream the bytes of one stored artifact."""
    row = await repository.require(artifact_id)
    stream = store.open_stream(row.storage_key)

    def _iterate() -> Iterator[bytes]:
        with stream as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                yield chunk

    return StreamingResponse(
        _iterate(),
        media_type=row.content_type,
        headers={
            "Content-Length": str(row.size_bytes),
            "X-Artifact-Sha256": row.sha256,
            "Content-Disposition": f'attachment; filename="{row.kind}-{row.sha256[:12]}"',
        },
    )
