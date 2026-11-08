"""Export endpoints: create reproducibility bundles and download them."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from trendsmapp.api.dependencies import (
    SettingsDependency,
    get_artifact_repository,
    get_object_store,
    get_session,
)
from trendsmapp.contracts.common import ArtifactRef
from trendsmapp.contracts.exports import (
    CreateExportRequest,
    CreateExportResponse,
    ExportResponse,
)
from trendsmapp.persistence.repositories.artifacts import ArtifactRepository
from trendsmapp.services.exports import ExportService
from trendsmapp.storage.base import ObjectStore

__all__ = ["router"]

router = APIRouter(prefix="/api/v1/exports", tags=["exports"])


def _service(
    session: Annotated[AsyncSession, Depends(get_session)],
    store: Annotated[ObjectStore, Depends(get_object_store)],
    settings: SettingsDependency,
) -> ExportService:
    """Build the export service for one request."""
    return ExportService(session=session, store=store, settings=settings)


ExportServiceDependency = Annotated[ExportService, Depends(_service)]


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=CreateExportResponse)
async def create_export(
    request: CreateExportRequest,
    service: ExportServiceDependency,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> CreateExportResponse:
    """Enqueue the export of one succeeded run as a verified bundle."""
    created = await service.create(request, idempotency_key=idempotency_key)
    return CreateExportResponse(**created)


@router.get("/{export_id}", response_model=ExportResponse)
async def get_export(
    export_id: str,
    service: ExportServiceDependency,
) -> ExportResponse:
    """Return one export with its bundle artifact and the manifest inside it."""
    found = await service.get_export(export_id)
    row = found["artifact"]
    return ExportResponse(
        export_id=found["export_id"],
        run_id=found["run_id"],
        job_id=found["job_id"],
        status=found["status"],
        artifact=ArtifactRef(
            artifact_id=row.id,
            kind=row.kind,
            sha256=row.sha256,
            size_bytes=row.size_bytes,
            content_type=row.content_type,
            schema_version=row.schema_version,
            created_at=row.created_at,
            media_type_detail=dict(row.details or {}),
        ),
        manifest=found["manifest"],
    )


@router.get("/{export_id}/download")
async def download_export(
    export_id: str,
    request: Request,
    service: ExportServiceDependency,
    repository: Annotated[ArtifactRepository, Depends(get_artifact_repository)],
    store: Annotated[ObjectStore, Depends(get_object_store)],
) -> StreamingResponse:
    """Stream the verified ZIP bundle of one export."""
    found = await service.get_export(export_id)
    row = await repository.require(found["artifact"].id)
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
        media_type="application/zip",
        headers={
            "Content-Length": str(row.size_bytes),
            "X-Artifact-Sha256": row.sha256,
            "Content-Disposition": f'attachment; filename="trendsmapp-bundle-{export_id}.zip"',
        },
    )
