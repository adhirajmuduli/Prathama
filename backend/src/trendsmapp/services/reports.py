"""PDF report service and workflow: one succeeded run becomes one rendered PDF.

The service validates the run and enqueues a ``report`` job keyed by the run id
(idempotent per run). The workflow collects the run's stored documents, tables,
manifest, and figure rasters, renders a deterministic PDF through
:mod:`trendsmapp.reporting.report`, and registers it as a ``report`` artifact
whose details carry the report id.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from trendsmapp.clock import utc_now
from trendsmapp.contracts.reports import CreateReportRequest
from trendsmapp.contracts.versions import ARTIFACT_SCHEMA_VERSION
from trendsmapp.domain.enums import JobType
from trendsmapp.domain.identifiers import new_artifact_id, new_job_id, new_report_id
from trendsmapp.errors import ConflictError, JobError, NotFoundError, ResourceLimitError
from trendsmapp.persistence.database import session_scope
from trendsmapp.persistence.repositories import (
    ArtifactRepository,
    DatasetRepository,
    JobRepository,
    RunRepository,
)
from trendsmapp.reporting import (
    build_manifest,
    build_report_pdf,
    dependency_lock_sha256,
    methods_record,
    result_tables,
)
from trendsmapp.settings import Settings
from trendsmapp.storage.base import ObjectStore
from trendsmapp.storage.paths import build_artifact_key
from trendsmapp.worker.handlers import JobExecutionContext, JobHandlerRegistry

__all__ = ["ReportService", "ReportWorkflow", "register_report_handler"]

_STAGE_LOAD: Final[str] = "load"
_STAGE_RENDER: Final[str] = "render"
_STAGE_STORE: Final[str] = "store"

#: A PDF embeds figures, so it can be large; cap it well below the bundle ceiling.
MAX_REPORT_BYTES: Final[int] = 64 * 1024 * 1024

#: At most this many figure rasters are embedded in one report.
MAX_REPORT_FIGURES: Final[int] = 24

_DOCUMENT_KINDS: Final[frozenset[str]] = frozenset({"metrics", "predictions", "explanations"})


class ReportService:
    """Creates report jobs and reads their PDF artifacts."""

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
        self._runs = RunRepository(session)
        self._jobs = JobRepository(session)
        self._artifacts = ArtifactRepository(session)

    async def create(
        self, request: CreateReportRequest, *, idempotency_key: str | None = None
    ) -> dict[str, str]:
        """Validate the run and enqueue the report job (idempotent per run)."""
        run = await self._runs.require(request.run_id)
        if run.status != "succeeded":
            raise ConflictError(
                "Only a succeeded run can be reported.",
                details={"run_id": run.id, "status": run.status},
            )
        key = f"report:{run.id}"
        existing = await self._jobs.find_by_idempotency_key(key)
        if existing is not None:
            payload = existing.payload or {}
            return {
                "report_id": str(payload.get("report_id", "")),
                "job_id": existing.id,
                "run_id": run.id,
                "status": existing.status,
            }
        report_id = new_report_id()
        request_hash = hashlib.sha256(
            json.dumps(
                {"run_id": run.id, "report_id": report_id},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        job, _created = await self._jobs.create(
            job_type=JobType.REPORT,
            job_id=new_job_id(),
            payload={
                "report_id": report_id,
                "run_id": run.id,
                "dataset_version_id": run.dataset_version_id,
            },
            idempotency_key=key,
            request_hash=request_hash,
            run_id=run.id,
            dataset_version_id=run.dataset_version_id,
        )
        return {
            "report_id": report_id,
            "job_id": job.id,
            "run_id": run.id,
            "status": "accepted",
        }

    async def get_report(self, report_id: str) -> dict[str, Any]:
        """Return one report: its PDF artifact, job status, and summary."""
        artifact = await self._artifacts.find_by_details("report", "report_id", report_id)
        if artifact is None:
            raise NotFoundError(
                "The requested report does not exist.", details={"report_id": report_id}
            )
        job = None
        if artifact.run_id is not None:
            job = await self._jobs.find_by_idempotency_key(f"report:{artifact.run_id}")
        return {
            "report_id": report_id,
            "run_id": artifact.run_id or "",
            "job_id": job.id if job is not None else None,
            "status": job.status if job is not None else "unknown",
            "artifact": artifact,
            "summary": dict(artifact.details or {}).get("summary", {}),
        }


class ReportWorkflow:
    """Executes one ``report`` job end to end."""

    async def __call__(self, context: JobExecutionContext) -> dict[str, Any]:
        """Render and store the PDF report of one run."""
        payload = context.payload
        report_id = str(payload.get("report_id", ""))
        run_id = str(payload.get("run_id", ""))
        if not report_id or not run_id:
            raise JobError(
                "The report job payload is missing the report or the run.",
                details={"has_report": bool(report_id), "has_run": bool(run_id)},
            )

        await self._progress(context, 0.05, _STAGE_LOAD)
        async with session_scope(context.session_factory) as session:
            runs = RunRepository(session)
            datasets = DatasetRepository(session)
            artifacts = ArtifactRepository(session)
            run = await runs.require(run_id)
            if run.status != "succeeded":
                raise JobError(
                    "Only a succeeded run can be reported.",
                    details={"run_id": run_id, "status": run.status},
                )
            version = await datasets.require_version(run.dataset_version_id)
            run_artifacts = await artifacts.list_for_run(run_id)

        documents: dict[str, dict[str, Any]] = {}
        figures: list[tuple[str, bytes]] = []
        manifest_artifacts: list[dict[str, Any]] = []
        for row in run_artifacts:
            manifest_artifacts.append(
                {
                    "artifact_id": row.id,
                    "kind": row.kind,
                    "sha256": row.sha256,
                    "size_bytes": row.size_bytes,
                    "content_type": row.content_type,
                    "bundle_path": f"artifacts/{row.kind}-{row.id}",
                }
            )
            if row.kind in _DOCUMENT_KINDS and row.content_type == "application/json":
                parsed = json.loads(context.object_store.get_bytes(row.storage_key).decode("utf-8"))
                if isinstance(parsed, dict):
                    documents[row.kind] = parsed
            elif (
                row.kind in {"raster", "figure"}
                and row.content_type == "image/png"
                and len(figures) < MAX_REPORT_FIGURES
            ):
                figures.append(
                    (f"{row.kind} {row.id[:12]}", context.object_store.get_bytes(row.storage_key))
                )

        await self._check_cancel(context)
        await self._progress(context, 0.4, _STAGE_RENDER)
        tables = result_tables(documents)
        table_hashes = {
            name: hashlib.sha256(payload_bytes).hexdigest()
            for name, payload_bytes in sorted(tables.items())
        }
        manifest = build_manifest(
            run={
                "id": run.id,
                "status": run.status,
                "recipe_hash": run.recipe_hash,
                "recipe": run.recipe,
                "seed": run.seed,
                "boundary_sha256": run.boundary_sha256,
                "created_at": run.created_at,
                "finished_at": run.finished_at,
            },
            dataset_version={"id": version.id, "normalized_sha256": version.normalized_sha256},
            artifacts=manifest_artifacts,
            tables=table_hashes,
            methods=methods_record(run.recipe or {}),
            generated_at=run.finished_at or run.created_at or utc_now(),
            lock_sha256=dependency_lock_sha256(),
        )
        pdf = build_report_pdf(
            manifest=manifest, documents=documents, tables=tables, figures=figures
        )
        if len(pdf) > MAX_REPORT_BYTES:
            raise ResourceLimitError(
                "The rendered report exceeds the size ceiling; it was not stored.",
                details={"report_bytes": len(pdf), "max_bytes": MAX_REPORT_BYTES},
            )
        if not pdf.startswith(b"%PDF-"):
            raise JobError(
                "The rendered report is not a valid PDF.", details={"report_id": report_id}
            )

        await self._check_cancel(context)
        await self._progress(context, 0.85, _STAGE_STORE)
        digest = hashlib.sha256(pdf).hexdigest()
        key = build_artifact_key("exports", digest, f"trendsmapp-report-{report_id}.pdf")
        context.object_store.put_bytes(key, pdf, content_type="application/pdf")
        async with session_scope(context.session_factory) as session:
            artifacts = ArtifactRepository(session)
            registered = await artifacts.register(
                artifact_id=new_artifact_id(),
                kind="report",
                sha256=digest,
                size_bytes=len(pdf),
                content_type="application/pdf",
                storage_key=key,
                schema_version=ARTIFACT_SCHEMA_VERSION,
                dataset_version_id=version.id,
                run_id=run_id,
                metadata={
                    "report_id": report_id,
                    "run_id": run_id,
                    "summary": {
                        "figures": len(figures),
                        "tables": len(tables),
                        "documents": sorted(documents),
                        "artifacts": len(manifest_artifacts),
                    },
                },
            )
        await self._progress(context, 1.0, None)
        return {
            "report_id": report_id,
            "artifact_id": registered.id,
            "run_id": run_id,
            "report_sha256": digest,
            "report_bytes": len(pdf),
            "figures": len(figures),
            "tables": len(tables),
        }

    async def _progress(
        self, context: JobExecutionContext, progress: float, stage: str | None
    ) -> None:
        await context.heartbeat.record_progress(context.job_id, progress=progress, stage=stage)

    async def _check_cancel(self, context: JobExecutionContext) -> None:
        if await context.cancellation_probe():
            raise JobError("The job was cancelled.", details={"reason": "cancelled"})


def register_report_handler(registry: JobHandlerRegistry) -> None:
    """Register the report handler on a workflow registry."""
    registry.register(JobType.REPORT, ReportWorkflow())
