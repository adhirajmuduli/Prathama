"""Upload-session and upload-part persistence."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from trendsmapp.clock import utc_now
from trendsmapp.errors import ConflictError, NotFoundError
from trendsmapp.persistence.models import UploadPartRow, UploadRow

__all__ = ["UploadRepository"]

OPEN_STATUS = "open"
COMPLETED_STATUS = "completed"
CANCELLED_STATUS = "cancelled"


class UploadRepository:
    """Reads and writes upload-session rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_session(
        self,
        *,
        upload_id: str,
        filename: str,
        extension: str,
        content_type: str | None,
        total_bytes: int,
        chunk_size_bytes: int,
        expected_sha256: str | None,
        expires_at: datetime,
        dataset_id: str | None = None,
    ) -> UploadRow:
        """Create an open upload session."""
        row = UploadRow(
            id=upload_id,
            filename=filename,
            content_type=content_type,
            extension=extension,
            total_bytes=total_bytes,
            chunk_size_bytes=chunk_size_bytes,
            expected_sha256=expected_sha256,
            status=OPEN_STATUS,
            dataset_id=dataset_id,
            created_at=utc_now(),
            expires_at=expires_at,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def get(self, upload_id: str) -> UploadRow | None:
        """Return an upload session by identifier."""
        return await self._session.get(UploadRow, upload_id)

    async def require(self, upload_id: str) -> UploadRow:
        """Return an upload session, raising when it does not exist."""
        row = await self.get(upload_id)
        if row is None:
            raise NotFoundError(
                "The requested upload session does not exist.",
                details={"upload_id": upload_id},
            )
        return row

    async def record_part(
        self,
        *,
        upload_id: str,
        part_number: int,
        size_bytes: int,
        sha256: str,
        storage_key: str,
    ) -> UploadPartRow:
        """Record one uploaded part, replacing an earlier attempt at the same number."""
        existing = await self.find_part(upload_id, part_number)
        if existing is not None:
            await self._session.delete(existing)
            await self._session.flush()
        row = UploadPartRow(
            upload_id=upload_id,
            part_number=part_number,
            size_bytes=size_bytes,
            sha256=sha256,
            storage_key=storage_key,
            created_at=utc_now(),
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def find_part(self, upload_id: str, part_number: int) -> UploadPartRow | None:
        """Return one uploaded part, if it exists."""
        result = await self._session.execute(
            select(UploadPartRow).where(
                UploadPartRow.upload_id == upload_id,
                UploadPartRow.part_number == part_number,
            )
        )
        return result.scalar_one_or_none()

    async def list_parts(self, upload_id: str) -> list[UploadPartRow]:
        """Return every uploaded part of a session, ordered by part number."""
        result = await self._session.execute(
            select(UploadPartRow)
            .where(UploadPartRow.upload_id == upload_id)
            .order_by(UploadPartRow.part_number)
        )
        return list(result.scalars())

    async def complete(self, upload_id: str) -> UploadRow:
        """Mark an upload session as completed."""
        row = await self.require(upload_id)
        if row.status != OPEN_STATUS:
            raise ConflictError(
                "The upload session is not open.",
                details={"upload_id": upload_id, "status": row.status},
            )
        row.status = COMPLETED_STATUS
        row.completed_at = utc_now()
        await self._session.flush()
        return row

    async def cancel(self, upload_id: str) -> UploadRow:
        """Cancel an open upload session and remove its part records."""
        row = await self.require(upload_id)
        if row.status == COMPLETED_STATUS:
            raise ConflictError(
                "A completed upload session cannot be cancelled.",
                details={"upload_id": upload_id},
            )
        row.status = CANCELLED_STATUS
        await self._session.execute(
            delete(UploadPartRow).where(UploadPartRow.upload_id == upload_id)
        )
        await self._session.flush()
        return row

    async def list_expired(self, *, now: datetime | None = None) -> list[UploadRow]:
        """Return open sessions whose expiry has passed."""
        reference = now or utc_now()
        result = await self._session.execute(
            select(UploadRow).where(
                UploadRow.status == OPEN_STATUS,
                UploadRow.expires_at < reference,
            )
        )
        return list(result.scalars())
