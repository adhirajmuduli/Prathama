"""The dataset application service: probe, create, and read dataset versions.

Creating a dataset version from an upload is a two-step decision made by the
analyst, not the system: the probe describes the file and proposes a mapping,
and the confirmed mapping is validated against the probe's evidence before any
job is enqueued. The ingest job then produces the sealed, immutable version.
"""

from __future__ import annotations

import io
import json
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

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
)
from trendsmapp.contracts.versions import ARTIFACT_SCHEMA_VERSION
from trendsmapp.domain.enums import JobType
from trendsmapp.domain.identifiers import (
    new_dataset_id,
    new_dataset_version_id,
    new_job_id,
)
from trendsmapp.errors import ConflictError, NotFoundError, ValidationError
from trendsmapp.hashing import sha256_bytes
from trendsmapp.ingestion.column_mapping import validate_mapping
from trendsmapp.ingestion.parser import probe_parse
from trendsmapp.persistence.models import ArtifactRow, DatasetVersionRow
from trendsmapp.persistence.repositories import (
    ArtifactRepository,
    DatasetRepository,
    JobRepository,
    ProvenanceRepository,
    UploadRepository,
)
from trendsmapp.persistence.repositories.uploads import COMPLETED_STATUS
from trendsmapp.settings import Settings
from trendsmapp.storage.base import ObjectStore

__all__ = ["DatasetService"]

#: How many bytes of a stored upload the probe reads.
_PROBE_BYTES: Final[int] = 64 * 1024

#: Artifact kinds that hold a JSON report document.
_REPORT_KINDS: Final[dict[str, str]] = {
    "parse": "parse_report",
    "normalization": "normalization_report",
    "qc": "qc_report",
}


class DatasetService:
    """Coordinates uploads, probes, mappings, and dataset versions."""

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
        self._datasets = DatasetRepository(session)
        self._jobs = JobRepository(session)
        self._artifacts = ArtifactRepository(session)
        self._provenance = ProvenanceRepository(session)

    async def probe(self, upload_id: str) -> ProbeResponse:
        """Describe the first rows of a completed upload and propose a mapping.

        The probe reads only a bounded prefix of the stored raw artifact, so it
        stays cheap on the API process; the full parse happens in the worker.
        """
        row = await self._uploads.require(upload_id)
        if row.status != COMPLETED_STATUS or not row.raw_artifact_id:
            raise ConflictError(
                "Only a completed upload can be probed.",
                details={"upload_id": upload_id, "status": row.status},
            )
        artifact = await self._artifacts.require(row.raw_artifact_id)
        with self._store.open_stream(artifact.storage_key) as handle:
            head = handle.read(_PROBE_BYTES)
        probe = probe_parse(
            io.BytesIO(head),
            filename=row.filename,
            content_type=row.content_type,
        )
        sniffed = probe.sniff
        return ProbeResponse(
            upload_id=upload_id,
            filename=row.filename,
            extension=row.extension,
            file_format=probe.file_type.format.value,
            content_type=probe.file_type.content_type,
            encoding=sniffed.encoding,
            delimiter=sniffed.delimiter,
            has_header=sniffed.has_header,
            fields=sniffed.fields,
            decimal_style=sniffed.decimal_style.value,
            layout=sniffed.layout.layout.value,
            layout_confidence=sniffed.layout.confidence,
            layout_evidence=sniffed.layout.evidence,
            layout_warnings=sniffed.layout.warnings,
            sniff_warnings=sniffed.warnings,
            sheet_names=probe.sheet_names,
            numeric_fields=probe.numeric_fields,
            date_fields=probe.date_fields,
            proposed_mapping=probe.proposed_mapping,
            proposal_warnings=probe.proposal_warnings,
        )

    async def create(self, request: CreateDatasetRequest) -> CreateDatasetResponse:
        """Create a dataset and its first version from an upload and a mapping.

        The mapping is validated against the probe's evidence here, so an
        impossible mapping never reaches the worker.
        """
        upload = await self._uploads.require(request.upload_id)
        if upload.status != COMPLETED_STATUS or not upload.raw_artifact_id:
            raise ConflictError(
                "Only a completed upload can become a dataset.",
                details={"upload_id": request.upload_id, "status": upload.status},
            )
        probe = await self.probe(request.upload_id)
        validation = validate_mapping(
            request.mapping,
            fields=probe.fields,
            numeric_fields=probe.numeric_fields,
            date_fields=probe.date_fields,
        )

        dataset_id = new_dataset_id()
        version_id = new_dataset_version_id()
        await self._datasets.create_dataset(
            dataset_id=dataset_id,
            name=request.name,
            description=request.description,
        )
        await self._datasets.create_version(
            version_id=version_id,
            dataset_id=dataset_id,
            version_number=1,
            schema_version=ARTIFACT_SCHEMA_VERSION,
        )
        upload.dataset_id = dataset_id
        await self._session.flush()

        artifact = await self._artifacts.require(upload.raw_artifact_id)
        key = f"ingest:{request.upload_id}:dataset:{dataset_id}"
        job, _created = await self._jobs.create(
            job_type=JobType.INGEST,
            job_id=new_job_id(),
            payload={
                "upload_id": request.upload_id,
                "raw_artifact_id": artifact.id,
                "dataset_id": dataset_id,
                "dataset_version_id": version_id,
                "filename": upload.filename,
                "extension": upload.extension,
                "sha256": artifact.sha256,
                "size_bytes": artifact.size_bytes,
                "content_type": artifact.content_type,
                "detected_format": (artifact.details or {}).get("detected_format"),
                "mapping": request.mapping.model_dump(mode="json"),
                "mapping_warnings": list(validation.warnings),
            },
            idempotency_key=key,
            request_hash=sha256_bytes(
                (request.upload_id + request.mapping.model_dump_json()).encode()
            ),
            dataset_version_id=version_id,
        )
        return CreateDatasetResponse(
            dataset_id=dataset_id,
            version_id=version_id,
            job_id=job.id,
        )

    async def get_dataset(self, dataset_id: str) -> DatasetResponse:
        """Return one dataset."""
        row = await self._datasets.get_dataset(dataset_id)
        if row is None:
            raise NotFoundError(
                "The requested dataset does not exist.",
                details={"dataset_id": dataset_id},
            )
        return DatasetResponse(
            dataset_id=row.id,
            name=row.name,
            description=row.description,
            current_version_id=row.current_version_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def list_datasets(self, *, limit: int = 100, offset: int = 0) -> DatasetListResponse:
        """Return a page of datasets, most recently updated first."""
        from trendsmapp.contracts.common import PageMeta

        rows = await self._datasets.list_datasets(limit=limit, offset=offset)
        total = await self._datasets.count_datasets()
        items = []
        for row in rows:
            items.append(
                DatasetResponse(
                    dataset_id=row.id,
                    name=row.name,
                    description=row.description,
                    current_version_id=row.current_version_id,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )
            )
        return DatasetListResponse(
            items=tuple(items),
            page=PageMeta(offset=offset, limit=limit, total=total),
        )

    async def list_versions(self, dataset_id: str) -> DatasetVersionListResponse:
        """Return every version of a dataset, oldest first."""
        await self.get_dataset(dataset_id)
        rows = await self._datasets.list_versions(dataset_id)
        items = []
        for row in rows:
            items.append(await self._version_response(row))
        return DatasetVersionListResponse(
            dataset_id=dataset_id,
            items=tuple(items),
        )

    async def get_version(self, version_id: str) -> DatasetVersionResponse:
        """Return one dataset version with its artifacts."""
        row = await self._datasets.require_version(version_id)
        return await self._version_response(row)

    async def preview(self, version_id: str, *, limit: int | None = None) -> PreviewResponse:
        """Return the first rows of a normalized dataset version."""
        row = await self._datasets.require_version(version_id)
        if row.normalized_artifact_id is None:
            raise ConflictError(
                "The dataset version has no normalized artifact yet.",
                details={"version_id": version_id},
            )
        artifact = await self._artifacts.require(row.normalized_artifact_id)
        cap = limit if limit is not None else self._settings.preview_row_limit
        cap = min(cap, self._settings.preview_row_limit)
        import pyarrow.parquet as pq

        with self._store.open_stream(artifact.storage_key) as handle:
            parquet = pq.ParquetFile(handle)
            table = parquet.read_row_group(0)
            columns = tuple(table.column_names)
            rows = tuple(tuple(record.values()) for record in table.slice(0, cap).to_pylist())
        return PreviewResponse(
            version_id=version_id,
            artifact_sha256=artifact.sha256,
            columns=columns,
            rows=rows,
            row_count=row.row_count,
            limit=cap,
        )

    async def report(self, version_id: str, kind: str) -> dict[str, Any]:
        """Return one stored JSON report document of a dataset version."""
        artifact_kind = _REPORT_KINDS.get(kind)
        if artifact_kind is None:
            raise ValidationError(
                f"Unknown report kind '{kind}'.",
                details={"allowed": sorted(_REPORT_KINDS)},
            )
        rows = await self._artifacts.list_for_version(version_id)
        artifact = next((row for row in rows if row.kind == artifact_kind), None)
        if artifact is None:
            raise NotFoundError(
                f"The dataset version has no {kind} report.",
                details={"version_id": version_id, "kind": kind},
            )
        payload = self._store.get_bytes(artifact.storage_key)
        document: dict[str, Any] = json.loads(payload.decode("utf-8"))
        return document

    async def provenance(self, version_id: str) -> ProvenanceListResponse:
        """Return the provenance events of a dataset version."""
        await self._datasets.require_version(version_id)
        rows = await self._provenance.list_for_version(version_id)
        from trendsmapp.contracts.common import ProvenanceRef

        return ProvenanceListResponse(
            version_id=version_id,
            items=tuple(
                ProvenanceRef(
                    provenance_id=row.id,
                    event_type=row.event_type,
                    occurred_at=row.occurred_at,
                    parent_artifact_ids=tuple(row.input_artifact_ids or []),
                    transformations=tuple(
                        str(item.get("name", "")) for item in (row.transformations or [])
                    ),
                )
                for row in rows
            ),
        )

    async def artifact_ref(self, artifact_id: str) -> ArtifactRef:
        """Return one artifact reference."""
        row = await self._artifacts.require(artifact_id)
        return _artifact_ref(row)

    async def _version_response(self, row: DatasetVersionRow) -> DatasetVersionResponse:
        """Build the contract response of one version row."""
        artifacts = await self._artifacts.list_for_version(row.id)
        normalized = None
        if row.normalized_artifact_id:
            normalized_row = await self._artifacts.get(row.normalized_artifact_id)
            if normalized_row is not None:
                normalized = _artifact_ref(normalized_row)
        return DatasetVersionResponse(
            version_id=row.id,
            dataset_id=row.dataset_id,
            version_number=row.version_number,
            schema_version=row.schema_version,
            sealed=row.sealed_at is not None,
            row_count=row.row_count,
            parameter_count=row.parameter_count,
            station_count=row.station_count,
            first_sampled_at=row.first_sampled_at,
            last_sampled_at=row.last_sampled_at,
            boundary_id=row.boundary_id,
            normalized_artifact=normalized,
            artifacts=tuple(_artifact_ref(item) for item in artifacts),
            created_at=row.created_at,
            sealed_at=row.sealed_at,
        )


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
