"""PDF report endpoints: render a report for a succeeded run and download it."""

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
from trendsmapp.contracts.reports import (
    CreateReportRequest,
    CreateReportResponse,
    ReportResponse,
)
from trendsmapp.persistence.repositories.artifacts import ArtifactRepository
from trendsmapp.services.reports import ReportService
from trendsmapp.storage.base import ObjectStore

__all__ = ["router"]

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])


def _service(
    session: Annotated[AsyncSession, Depends(get_session)],
    store: Annotated[ObjectStore, Depends(get_object_store)],
    settings: SettingsDependency,
) -> ReportService:
    """Build the report service for one request."""
    return ReportService(session=session, store=store, settings=settings)


ReportServiceDependency = Annotated[ReportService, Depends(_service)]


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=CreateReportResponse)
async def create_report(
    request: CreateReportRequest,
    service: ReportServiceDependency,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> CreateReportResponse:
    """Enqueue the PDF report of one succeeded run. Idempotent per run."""
    created = await service.create(request, idempotency_key=idempotency_key)
    return CreateReportResponse(**created)


@router.get("/{report_id}", response_model=ReportResponse)
async def get_report(
    report_id: str,
    service: ReportServiceDependency,
) -> ReportResponse:
    """Return one report with its PDF artifact and summary."""
    found = await service.get_report(report_id)
    row = found["artifact"]
    return ReportResponse(
        report_id=found["report_id"],
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
        summary=found["summary"],
    )


@router.get("/{report_id}/download")
async def download_report(
    report_id: str,
    request: Request,
    service: ReportServiceDependency,
    repository: Annotated[ArtifactRepository, Depends(get_artifact_repository)],
    store: Annotated[ObjectStore, Depends(get_object_store)],
) -> StreamingResponse:
    """Stream the rendered PDF report."""
    found = await service.get_report(report_id)
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
        media_type="application/pdf",
        headers={
            "Content-Length": str(row.size_bytes),
            "X-Artifact-Sha256": row.sha256,
            "Content-Disposition": f'attachment; filename="trendsmapp-report-{report_id}.pdf"',
        },
    )
