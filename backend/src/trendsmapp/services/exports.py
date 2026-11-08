"""Export service and workflow: one succeeded run becomes one verified bundle.

The service validates the run and enqueues an ``export`` job keyed by the run
id, so exporting the same run twice is idempotent. The workflow collects the
run's artifacts and the dataset version's reports, builds the manifest,
methods record, and CSV tables through :mod:`trendsmapp.reporting`, packs a
deterministic ZIP, verifies it before storing, and registers the bundle as an
``export_bundle`` artifact whose id is the export id.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from trendsmapp.clock import utc_now
from trendsmapp.constants import MAX_EXPORT_BUNDLE_BYTES
from trendsmapp.contracts.exports import CreateExportRequest
from trendsmapp.contracts.versions import ARTIFACT_SCHEMA_VERSION
from trendsmapp.domain.enums import JobType
from trendsmapp.domain.identifiers import new_artifact_id, new_export_id, new_job_id
from trendsmapp.errors import ConflictError, JobError, NotFoundError, ResourceLimitError
from trendsmapp.persistence.database import session_scope
from trendsmapp.persistence.repositories import (
    ArtifactRepository,
    DatasetRepository,
    JobRepository,
    RunRepository,
)
from trendsmapp.reporting import (
    build_bundle,
    build_manifest,
    bundle_sha256,
    dependency_lock_sha256,
    methods_record,
    read_bundle_manifest,
    result_tables,
    verify_bundle,
)
from trendsmapp.settings import Settings
from trendsmapp.storage.base import ObjectStore
from trendsmapp.storage.paths import build_artifact_key, safe_filename
from trendsmapp.worker.handlers import JobExecutionContext, JobHandlerRegistry

__all__ = ["ExportService", "ExportWorkflow", "register_export_handler"]

_STAGE_LOAD: Final[str] = "load"
_STAGE_COLLECT: Final[str] = "collect"
_STAGE_TABLES: Final[str] = "tables"
_STAGE_BUNDLE: Final[str] = "bundle"
_STAGE_STORE: Final[str] = "store"

_CONTENT_TYPE_EXTENSIONS: Final[dict[str, str]] = {
    "application/json": "json",
    "application/octet-stream": "bin",
    "application/parquet": "parquet",
    "application/vnd.apache.parquet": "parquet",
    "image/png": "png",
    "image/tiff": "tif",
    "video/mp4": "mp4",
    "text/csv": "csv",
    "text/plain": "txt",
    "application/zip": "zip",
}

_REPORT_KINDS: Final[frozenset[str]] = frozenset(
    {"parse_report", "normalization_report", "qc_report", "provenance", "normalized_dataset"}
)


def _bundle_name(kind: str, artifact_id: str, content_type: str) -> str:
    """Return the archive-relative file name of one artifact."""
    extension = _CONTENT_TYPE_EXTENSIONS.get(content_type, "bin")
    return f"{safe_filename(kind)}-{artifact_id}.{extension}"


class ExportService:
    """Creates export jobs and reads their bundle artifacts."""

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
        self, request: CreateExportRequest, *, idempotency_key: str | None = None
    ) -> dict[str, str]:
        """Validate the run and enqueue the export job.

        Only a succeeded run can be exported. The export id is derived from
        the run id through the job idempotency key, so repeating the same
        request returns the original export.
        """
        run = await self._runs.require(request.run_id)
        if run.status != "succeeded":
            raise ConflictError(
                "Only a succeeded run can be exported.",
                details={"run_id": run.id, "status": run.status},
            )
        key = f"export:{run.id}"
        existing = await self._jobs.find_by_idempotency_key(key)
        if existing is not None:
            payload = existing.payload or {}
            return {
                "export_id": str(payload.get("export_id", "")),
                "job_id": existing.id,
                "run_id": run.id,
                "status": existing.status,
            }
        export_id = new_export_id()
        request_hash = hashlib.sha256(
            json.dumps(
                {"run_id": run.id, "export_id": export_id},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        job, _created = await self._jobs.create(
            job_type=JobType.EXPORT,
            job_id=new_job_id(),
            payload={
                "export_id": export_id,
                "run_id": run.id,
                "dataset_version_id": run.dataset_version_id,
            },
            idempotency_key=key,
            request_hash=request_hash,
            run_id=run.id,
            dataset_version_id=run.dataset_version_id,
        )
        return {
            "export_id": export_id,
            "job_id": job.id,
            "run_id": run.id,
            "status": "accepted",
        }

    async def get_export(self, export_id: str) -> dict[str, Any]:
        """Return one export: its bundle artifact, job status, and manifest."""
        artifact = await self._artifacts.find_by_export_id(export_id)
        if artifact is None:
            raise NotFoundError(
                "The requested export does not exist.", details={"export_id": export_id}
            )
        job = None
        if artifact.run_id is not None:
            job = await self._jobs.find_by_idempotency_key(f"export:{artifact.run_id}")
        manifest: dict[str, Any] = {}
        payload = self._store.get_bytes(artifact.storage_key)
        try:
            manifest = read_bundle_manifest(payload)
        except (ValueError, KeyError):
            manifest = {}
        return {
            "export_id": export_id,
            "run_id": artifact.run_id or "",
            "job_id": job.id if job is not None else None,
            "status": job.status if job is not None else "unknown",
            "artifact": artifact,
            "manifest": manifest,
        }


class ExportWorkflow:
    """Executes one ``export`` job end to end."""

    async def __call__(self, context: JobExecutionContext) -> dict[str, Any]:
        """Collect, pack, verify, and store the bundle of one run."""
        payload = context.payload
        export_id = str(payload.get("export_id", ""))
        run_id = str(payload.get("run_id", ""))
        if not export_id or not run_id:
            raise JobError(
                "The export job payload is missing the export or the run.",
                details={"has_export": bool(export_id), "has_run": bool(run_id)},
            )

        await self._progress(context, 0.05, _STAGE_LOAD)
        async with session_scope(context.session_factory) as session:
            runs = RunRepository(session)
            datasets = DatasetRepository(session)
            artifacts = ArtifactRepository(session)
            run = await runs.require(run_id)
            if run.status != "succeeded":
                raise JobError(
                    "Only a succeeded run can be exported.",
                    details={"run_id": run_id, "status": run.status},
                )
            version = await datasets.require_version(run.dataset_version_id)
            run_artifacts = await artifacts.list_for_run(run_id)
            version_artifacts = [
                row
                for row in await artifacts.list_for_version(version.id)
                if row.kind in _REPORT_KINDS
            ]

        await self._check_cancel(context)
        await self._progress(context, 0.2, _STAGE_COLLECT)
        total_bytes = sum(row.size_bytes for row in (*run_artifacts, *version_artifacts))
        if total_bytes > MAX_EXPORT_BUNDLE_BYTES:
            raise ResourceLimitError(
                "The run's artifacts exceed the export bundle ceiling; the bundle was not created.",
                details={
                    "total_bytes": total_bytes,
                    "max_bytes": MAX_EXPORT_BUNDLE_BYTES,
                    "run_id": run_id,
                },
            )

        documents: dict[str, dict[str, Any]] = {}
        files: list[tuple[str, bytes]] = []
        manifest_artifacts: list[dict[str, Any]] = []
        for row in run_artifacts:
            path = f"artifacts/{_bundle_name(row.kind, row.id, row.content_type)}"
            data = context.object_store.get_bytes(row.storage_key)
            files.append((path, data))
            manifest_artifacts.append(
                {
                    "artifact_id": row.id,
                    "kind": row.kind,
                    "sha256": row.sha256,
                    "size_bytes": row.size_bytes,
                    "content_type": row.content_type,
                    "bundle_path": path,
                }
            )
            if (
                row.kind in {"metrics", "predictions", "explanations"}
                and row.content_type == "application/json"
            ):
                parsed = json.loads(data.decode("utf-8"))
                if isinstance(parsed, dict):
                    documents[row.kind] = parsed
        for row in version_artifacts:
            path = f"dataset/{_bundle_name(row.kind, row.id, row.content_type)}"
            data = context.object_store.get_bytes(row.storage_key)
            files.append((path, data))
            manifest_artifacts.append(
                {
                    "artifact_id": row.id,
                    "kind": row.kind,
                    "sha256": row.sha256,
                    "size_bytes": row.size_bytes,
                    "content_type": row.content_type,
                    "bundle_path": path,
                }
            )

        await self._check_cancel(context)
        await self._progress(context, 0.5, _STAGE_TABLES)
        tables = result_tables(documents)
        table_hashes: dict[str, str] = {}
        for name in sorted(tables):
            payload_bytes = tables[name]
            table_hashes[name] = hashlib.sha256(payload_bytes).hexdigest()
            files.append((f"tables/{name}", payload_bytes))
        methods = methods_record(run.recipe or {})
        files.append(
            (
                "methods.json",
                json.dumps(methods, indent=2, sort_keys=True, default=str).encode("utf-8"),
            )
        )
        files.append(("data-dictionary.json", _data_dictionary(run, documents)))
        files.append(("README.md", _readme(run).encode("utf-8")))

        await self._check_cancel(context)
        await self._progress(context, 0.7, _STAGE_BUNDLE)
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
            methods=methods,
            generated_at=run.finished_at or run.created_at or utc_now(),
            lock_sha256=dependency_lock_sha256(),
        )
        bundle = build_bundle(manifest=manifest, files=files)
        if len(bundle) > MAX_EXPORT_BUNDLE_BYTES:
            raise ResourceLimitError(
                "The export bundle exceeds the size ceiling; it was not stored.",
                details={"bundle_bytes": len(bundle), "max_bytes": MAX_EXPORT_BUNDLE_BYTES},
            )
        verification = verify_bundle(bundle)
        if not verification.ok:
            raise JobError(
                "The export bundle failed its own checksum verification; it was not stored.",
                details={
                    "mismatches": list(verification.mismatches),
                    "missing": list(verification.missing),
                },
            )

        await self._check_cancel(context)
        await self._progress(context, 0.9, _STAGE_STORE)
        digest = bundle_sha256(bundle)
        key = build_artifact_key("exports", digest, f"trendsmapp-bundle-{export_id}.zip")
        context.object_store.put_bytes(key, bundle, content_type="application/zip")
        async with session_scope(context.session_factory) as session:
            artifacts = ArtifactRepository(session)
            registered = await artifacts.register(
                artifact_id=new_artifact_id(),
                kind="export_bundle",
                sha256=digest,
                size_bytes=len(bundle),
                content_type="application/zip",
                storage_key=key,
                schema_version=ARTIFACT_SCHEMA_VERSION,
                dataset_version_id=version.id,
                run_id=run_id,
                metadata={
                    "export_id": export_id,
                    "run_id": run_id,
                    "manifest_sha256": hashlib.sha256(
                        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
                    ).hexdigest(),
                    "files": verification.checked_files,
                    "verified": True,
                },
            )
        await self._progress(context, 1.0, None)
        return {
            "export_id": export_id,
            "artifact_id": registered.id,
            "run_id": run_id,
            "bundle_sha256": digest,
            "bundle_bytes": len(bundle),
            "files": verification.checked_files,
            "verified": True,
        }

    async def _progress(
        self, context: JobExecutionContext, progress: float, stage: str | None
    ) -> None:
        """Record job progress and heartbeat in one call."""
        await context.heartbeat.record_progress(context.job_id, progress=progress, stage=stage)

    async def _check_cancel(self, context: JobExecutionContext) -> None:
        """Raise when cancellation was requested for the job."""
        if await context.cancellation_probe():
            raise JobError("The job was cancelled.", details={"reason": "cancelled"})


def _data_dictionary(run: Any, documents: dict[str, dict[str, Any]]) -> bytes:
    """Describe every parameter the run touched, from the versioned registry."""
    from trendsmapp.normalization.parameters import get_parameter_registry

    registry = get_parameter_registry()
    wanted = {str(run.recipe.get("target_parameter_id"))} if run.recipe else set()
    metrics = documents.get("metrics") or {}
    frames = metrics.get("frames")
    if isinstance(frames, list):
        for frame in frames:
            if isinstance(frame, dict) and frame.get("parameter_id"):
                wanted.add(str(frame["parameter_id"]))
    entries = []
    for parameter_id in sorted(wanted):
        if not parameter_id or parameter_id == "None":
            continue
        parameter = registry.get(parameter_id)
        if parameter is None:
            entries.append({"id": parameter_id, "registered": False})
            continue
        entries.append(
            {
                "id": parameter.id,
                "label": parameter.label,
                "display_name": parameter.display_name,
                "canonical_unit": parameter.canonical_unit,
                "dimension": parameter.dimension,
                "aliases": list(parameter.aliases),
                "registered": True,
            }
        )
    return json.dumps({"parameters": entries}, indent=2, sort_keys=True).encode("utf-8")


def _readme(run: Any) -> str:
    """Return the bundle README with the reproduction command."""
    return (
        "# Trendsmapp export bundle\n\n"
        f"Run: `{run.id}`\n"
        f"Recipe SHA-256: `{run.recipe_hash}`\n\n"
        "Contents: `manifest.json` (full reproducibility record), "
        "`checksums.sha256` (SHA-256 of every member), `methods.json`, "
        "`data-dictionary.json`, `tables/` (CSV result tables), `artifacts/` "
        "(run outputs), `dataset/` (dataset version reports).\n\n"
        "Verify: `trendsmapp reproduce <this-file.zip>`\n"
    )


def register_export_handler(registry: JobHandlerRegistry) -> None:
    """Register the export handler on a workflow registry."""
    registry.register(JobType.EXPORT, ExportWorkflow())
