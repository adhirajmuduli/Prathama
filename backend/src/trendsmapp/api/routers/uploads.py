"""Upload session endpoints.

The upload flow is chunked and idempotent: create a session, PUT parts with
optional ``Content-Range`` headers, complete to assemble and verify the whole
upload, or abort to cancel. Completing stores the immutable raw artifact and
enqueues the ingest job.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, Header, status
from sqlalchemy.ext.asyncio import AsyncSession

from trendsmapp.api.dependencies import (
    SettingsDependency,
    get_object_store,
    get_session,
)
from trendsmapp.contracts.uploads import (
    AbortUploadResponse,
    CompleteUploadResponse,
    CreateUploadRequest,
    PartUploadResponse,
    UploadSessionResponse,
    UploadStatusResponse,
)
from trendsmapp.services.uploads import UploadService
from trendsmapp.storage.base import ObjectStore

__all__ = ["router"]

router = APIRouter(prefix="/api/v1/uploads", tags=["uploads"])


def _service(
    session: Annotated[AsyncSession, Depends(get_session)],
    store: Annotated[ObjectStore, Depends(get_object_store)],
    settings: SettingsDependency,
) -> UploadService:
    """Build the upload service for one request."""
    return UploadService(session=session, store=store, settings=settings)


UploadServiceDependency = Annotated[UploadService, Depends(_service)]


@router.post("", response_model=UploadSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_upload(
    request: CreateUploadRequest,
    service: UploadServiceDependency,
) -> UploadSessionResponse:
    """Create an upload session and return its part plan."""
    return await service.create_session(request)


@router.get("/{upload_id}", response_model=UploadStatusResponse)
async def get_upload(
    upload_id: str,
    service: UploadServiceDependency,
) -> UploadStatusResponse:
    """Return the current state of an upload session."""
    return await service.get_status(upload_id)


@router.put("/{upload_id}/parts/{part_number}", response_model=PartUploadResponse)
async def put_part(
    upload_id: str,
    part_number: int,
    service: UploadServiceDependency,
    payload: bytes = Body(...),
    content_range: Annotated[str | None, Header(alias="Content-Range")] = None,
) -> PartUploadResponse:
    """Store one part of an upload after range and size validation."""
    return await service.put_part(
        upload_id=upload_id,
        part_number=part_number,
        payload=payload,
        content_range=content_range,
    )


@router.post("/{upload_id}/complete", response_model=CompleteUploadResponse)
async def complete_upload(
    upload_id: str,
    service: UploadServiceDependency,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> CompleteUploadResponse:
    """Assemble, verify, and store the upload, then enqueue the ingest job."""
    return await service.complete(upload_id=upload_id, idempotency_key=idempotency_key)


@router.post("/{upload_id}/abort", response_model=AbortUploadResponse)
async def abort_upload(
    upload_id: str,
    service: UploadServiceDependency,
) -> AbortUploadResponse:
    """Cancel an open upload session and delete its stored parts."""
    return await service.abort(upload_id=upload_id)
