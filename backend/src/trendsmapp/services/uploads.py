"""The upload application service: chunked sessions over the object store.

The service owns the upload lifecycle: creating a session with a validated
plan, accepting parts with per-part digest verification, assembling a completed
upload into its content-addressed raw artifact, and aborting sessions. It is
the only component that turns client bytes into stored bytes, and it never
writes a byte that is not digest-verified first.

Idempotency: completing the same session with the same idempotency key returns
the job that was already enqueued instead of enqueuing a second one.
"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime, timedelta
from typing import BinaryIO, Final, cast

from sqlalchemy.ext.asyncio import AsyncSession

from trendsmapp.clock import utc_now
from trendsmapp.constants import (
    CHUNK_SIZE_BOUNDS_BYTES,
    DEFAULT_UPLOAD_CHUNK_BYTES,
)
from trendsmapp.contracts.common import ArtifactRef
from trendsmapp.contracts.uploads import (
    AbortUploadResponse,
    CompleteUploadResponse,
    CreateUploadRequest,
    PartPlanResponse,
    PartUploadResponse,
    UploadSessionResponse,
    UploadStatusResponse,
)
from trendsmapp.contracts.versions import ARTIFACT_SCHEMA_VERSION
from trendsmapp.domain.enums import JobType
from trendsmapp.domain.identifiers import new_artifact_id, new_upload_id
from trendsmapp.errors import ConflictError, ResourceLimitError, ValidationError
from trendsmapp.hashing import sha256_bytes
from trendsmapp.ingestion.chunking import (
    StoredPartRef,
    assemble_parts,
    plan_parts,
    validate_part_request,
)
from trendsmapp.ingestion.file_types import inspect_file_type
from trendsmapp.ingestion.security import enforce_upload_size
from trendsmapp.persistence.models import ArtifactRow, UploadRow
from trendsmapp.persistence.repositories.artifacts import ArtifactRepository
from trendsmapp.persistence.repositories.jobs import JobRepository
from trendsmapp.persistence.repositories.uploads import (
    COMPLETED_STATUS,
    OPEN_STATUS,
    UploadRepository,
)
from trendsmapp.settings import Settings
from trendsmapp.storage.base import ObjectStore
from trendsmapp.storage.paths import build_raw_upload_key, build_upload_part_key

__all__ = ["UploadService"]

#: Bytes read from an assembled upload to validate its file type.
_HEAD_BYTES: Final[int] = 64 * 1024

#: The idempotency-key prefix for ingest jobs enqueued by complete().
_INGEST_KEY_PREFIX: Final[str] = "ingest"


def _ensure_aware(value: datetime) -> datetime:
    """Return a datetime as timezone-aware UTC.

    SQLite returns naive datetimes for ``DateTime(timezone=True)`` columns, so
    comparisons against :func:`trendsmapp.clock.utc_now` must normalize first.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class UploadService:
    """Coordinates upload sessions, the object store, and the job queue."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        store: ObjectStore,
        settings: Settings,
    ) -> None:
        self._session = session
        self._store = store
        self._settings = settings
        self._uploads = UploadRepository(session)
        self._artifacts = ArtifactRepository(session)
        self._jobs = JobRepository(session)

    async def create_session(self, request: CreateUploadRequest) -> UploadSessionResponse:
        """Create an open upload session with its part plan."""
        from trendsmapp.ingestion.file_types import normalized_extension

        extension = normalized_extension(request.filename)
        enforce_upload_size(request.size_bytes, maximum_bytes=self._settings.upload_max_bytes)

        chunk_size = request.chunk_size_bytes or self._settings.upload_chunk_bytes
        low, high = CHUNK_SIZE_BOUNDS_BYTES
        if not low <= chunk_size <= high:
            raise ValidationError(
                "The chunk size is outside the accepted bounds.",
                details={
                    "chunk_size_bytes": chunk_size,
                    "bounds": [low, high],
                    "default_bytes": DEFAULT_UPLOAD_CHUNK_BYTES,
                },
            )

        open_count = await self._uploads.count_open()
        if open_count >= self._settings.upload_max_concurrent_sessions:
            raise ResourceLimitError(
                "The maximum number of concurrent upload sessions is reached.",
                details={
                    "open_sessions": open_count,
                    "maximum": self._settings.upload_max_concurrent_sessions,
                },
            )

        upload_id = new_upload_id()
        now = utc_now()
        expires_at = now + timedelta(seconds=self._settings.upload_session_ttl_seconds)
        row = await self._uploads.create_session(
            upload_id=upload_id,
            filename=request.filename,
            extension=extension,
            content_type=request.content_type,
            total_bytes=request.size_bytes,
            chunk_size_bytes=chunk_size,
            expected_sha256=request.sha256,
            expires_at=expires_at,
            dataset_id=request.dataset_id,
        )
        plans = plan_parts(request.size_bytes, chunk_size)
        return UploadSessionResponse(
            upload_id=row.id,
            filename=row.filename,
            extension=row.extension,
            size_bytes=row.total_bytes,
            chunk_size_bytes=row.chunk_size_bytes,
            part_count=len(plans),
            parts=tuple(
                PartPlanResponse(
                    part_number=plan.part_number,
                    start_byte=plan.start_byte,
                    end_byte=plan.end_byte,
                    size_bytes=plan.size_bytes,
                )
                for plan in plans
            ),
            expires_at=row.expires_at,
            created_at=row.created_at,
        )

    async def put_part(
        self,
        *,
        upload_id: str,
        part_number: int,
        payload: bytes,
        content_range: str | None,
    ) -> PartUploadResponse:
        """Store one part after validating its declared range and size."""
        row = await self._require_open(upload_id)
        plan = validate_part_request(
            part_number=part_number,
            content_range=content_range,
            total_bytes=row.total_bytes,
            chunk_size=row.chunk_size_bytes,
        )
        if len(payload) != plan.size_bytes:
            raise ValidationError(
                "The part size does not match the declared plan.",
                details={
                    "part_number": part_number,
                    "expected_bytes": plan.size_bytes,
                    "received_bytes": len(payload),
                },
            )
        digest = sha256_bytes(payload)
        key = build_upload_part_key(upload_id, part_number)
        stored = self._store.put_bytes(key, payload, content_type="application/octet-stream")
        if stored.sha256 != digest:
            raise ConflictError(
                "The stored part does not match its computed digest.",
                details={"key": key},
            )
        await self._uploads.record_part(
            upload_id=upload_id,
            part_number=part_number,
            size_bytes=stored.size_bytes,
            sha256=stored.sha256,
            storage_key=key,
        )
        return PartUploadResponse(
            upload_id=upload_id,
            part_number=part_number,
            size_bytes=stored.size_bytes,
            sha256=stored.sha256,
        )

    async def get_status(self, upload_id: str) -> UploadStatusResponse:
        """Return the current state of an upload session."""
        row = await self._uploads.require(upload_id)
        parts = await self._uploads.list_parts(upload_id)
        plans = plan_parts(row.total_bytes, row.chunk_size_bytes)
        received = {part.part_number for part in parts}
        missing = tuple(plan.part_number for plan in plans if plan.part_number not in received)
        artifact: ArtifactRef | None = None
        job_id: str | None = None
        if row.status == COMPLETED_STATUS and row.raw_artifact_id:
            artifact_row = await self._artifacts.get(row.raw_artifact_id)
            if artifact_row is not None:
                artifact = self._artifact_ref(artifact_row)
            job_id = row.ingest_job_id
        return UploadStatusResponse(
            upload_id=row.id,
            status=row.status,
            filename=row.filename,
            extension=row.extension,
            size_bytes=row.total_bytes,
            sha256=row.expected_sha256,
            parts_received=tuple(sorted(received)),
            missing_parts=missing,
            artifact=artifact,
            job_id=job_id,
            expires_at=row.expires_at,
            created_at=row.created_at,
            completed_at=row.completed_at,
        )

    async def complete(
        self, *, upload_id: str, idempotency_key: str | None = None
    ) -> CompleteUploadResponse:
        """Assemble the parts, store the raw artifact, and enqueue the ingest job.

        The upload is verified end to end before anything is registered: every
        part digest, the assembled size, the declared digest, and the file type
        from the leading bytes. Only then is the raw artifact stored
        immutably and the ingest job enqueued.
        """
        row = await self._uploads.require(upload_id)
        if row.status == COMPLETED_STATUS:
            return await self._repeat_complete(upload_id, row, idempotency_key)
        row = await self._require_open(upload_id)

        parts = await self._uploads.list_parts(upload_id)
        plans = plan_parts(row.total_bytes, row.chunk_size_bytes)
        by_number = {part.part_number: part for part in parts}
        missing = [plan.part_number for plan in plans if plan.part_number not in by_number]
        if missing:
            raise ValidationError(
                "The upload is incomplete; parts are still missing.",
                details={"missing_parts": missing, "part_count": len(plans)},
            )
        refs = tuple(
            StoredPartRef(
                key=by_number[plan.part_number].storage_key,
                sha256=by_number[plan.part_number].sha256,
                size_bytes=by_number[plan.part_number].size_bytes,
            )
            for plan in plans
        )

        with tempfile.TemporaryFile() as raw_spool:
            assembled: BinaryIO = cast(BinaryIO, raw_spool)
            result = assemble_parts(
                store=self._store,
                parts=refs,
                destination=assembled,
                expected_total_bytes=row.total_bytes,
                expected_sha256=row.expected_sha256,
            )
            assembled.seek(0)
            head = assembled.read(_HEAD_BYTES)
            assembled.seek(0)
            verdict = inspect_file_type(
                filename=row.filename, content_type=row.content_type, head=head
            )
            raw_key = build_raw_upload_key(upload_id, result.sha256, row.filename)
            stored = self._store.put_stream(
                raw_key,
                cast(BinaryIO, raw_spool),
                content_type=verdict.content_type or "application/octet-stream",
                expected_size=result.size_bytes,
            )

        artifact_id = new_artifact_id()
        artifact_row = await self._artifacts.register(
            artifact_id=artifact_id,
            kind="raw_upload",
            sha256=stored.sha256,
            size_bytes=stored.size_bytes,
            content_type=stored.content_type,
            storage_key=raw_key,
            schema_version=ARTIFACT_SCHEMA_VERSION,
            metadata={
                "upload_id": upload_id,
                "filename": row.filename,
                "extension": row.extension,
                "detected_format": verdict.format.value,
                "mime_warnings": list(verdict.warnings),
            },
        )
        await self._uploads.complete(upload_id)

        key = f"{_INGEST_KEY_PREFIX}:{upload_id}" + (
            f":{idempotency_key}" if idempotency_key else ""
        )
        job, _created = await self._jobs.create(
            job_type=JobType.INGEST,
            payload={
                "upload_id": upload_id,
                "raw_artifact_id": artifact_id,
                "filename": row.filename,
                "extension": row.extension,
                "sha256": stored.sha256,
                "size_bytes": stored.size_bytes,
                "content_type": stored.content_type,
                "detected_format": verdict.format.value,
            },
            idempotency_key=key if idempotency_key else None,
            request_hash=sha256_bytes(f"{upload_id}|{artifact_id}|{stored.sha256}".encode()),
        )
        await self._uploads.record_result(
            upload_id=upload_id, raw_artifact_id=artifact_id, ingest_job_id=job.id
        )
        artifact_ref = self._artifact_ref(artifact_row)
        return CompleteUploadResponse(
            upload_id=upload_id,
            artifact=artifact_ref,
            job_id=job.id,
        )

    async def abort(self, *, upload_id: str) -> AbortUploadResponse:
        """Cancel an open session and delete its stored parts."""
        row = await self._uploads.require(upload_id)
        if row.status != OPEN_STATUS:
            raise ConflictError(
                "Only an open upload session can be aborted.",
                details={"upload_id": upload_id, "status": row.status},
            )
        await self._uploads.cancel(upload_id)
        prefix = f"uploads/{upload_id}/parts/"
        for key in list(self._store.list_prefix(prefix)):
            self._store.delete(key)
        return AbortUploadResponse(upload_id=upload_id)

    async def _require_open(self, upload_id: str) -> UploadRow:
        """Return the session row, rejecting unknown, closed, or expired sessions."""
        row = await self._uploads.require(upload_id)
        if row.status != OPEN_STATUS:
            raise ConflictError(
                "The upload session is not open.",
                details={"upload_id": upload_id, "status": row.status},
            )
        if _ensure_aware(row.expires_at) <= utc_now():
            raise ConflictError(
                "The upload session has expired.",
                details={"upload_id": upload_id, "expires_at": row.expires_at},
            )
        return row

    async def _repeat_complete(
        self, upload_id: str, row: UploadRow, idempotency_key: str | None
    ) -> CompleteUploadResponse:
        """Return the result of an already completed session for a retrying client."""
        if not idempotency_key:
            raise ConflictError(
                "The upload session is already completed.",
                details={"upload_id": upload_id, "status": row.status},
            )
        key = f"{_INGEST_KEY_PREFIX}:{upload_id}:{idempotency_key}"
        job = await self._jobs.find_by_idempotency_key(key)
        if job is None:
            raise ConflictError(
                "The upload session is already completed without this idempotency key.",
                details={"upload_id": upload_id},
            )
        artifact_row = (
            await self._artifacts.get(row.raw_artifact_id) if row.raw_artifact_id else None
        )
        if artifact_row is None:
            raise ConflictError(
                "The completed upload has no raw artifact.",
                details={"upload_id": upload_id},
            )
        return CompleteUploadResponse(
            upload_id=upload_id,
            artifact=self._artifact_ref(artifact_row),
            job_id=job.id,
        )

    @staticmethod
    def _artifact_ref(row: ArtifactRow) -> ArtifactRef:
        """Build the contract reference of an artifact row."""
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
