"""The ingest workflow: the worker's handler for ``ingest`` jobs.

One ingest job turns a stored raw upload into a sealed, immutable dataset
version. The stages are recorded on the job row as they complete, and a
cancellation request between stages stops the job cleanly. Every artifact the
run produces is content-addressed, digest-verified, and registered in the
database before the version is sealed.
"""

from __future__ import annotations

import hashlib
import io
import json
import tempfile
from typing import Any, BinaryIO, Final, cast

from trendsmapp.contracts.versions import ARTIFACT_SCHEMA_VERSION
from trendsmapp.domain.enums import JobType
from trendsmapp.domain.identifiers import new_artifact_id
from trendsmapp.domain.models import Observation
from trendsmapp.errors import JobError
from trendsmapp.ingestion.column_mapping import ColumnMapping
from trendsmapp.ingestion.parser import ParseReport, ParseSession
from trendsmapp.ingestion.sniffing import DecimalStyle
from trendsmapp.normalization.parameters import get_parameter_registry
from trendsmapp.normalization.pipeline import (
    NormalizationPipeline,
    NormalizationReport,
    NormalizationResult,
    write_canonical_parquet,
)
from trendsmapp.persistence.database import session_scope
from trendsmapp.persistence.repositories import (
    ArtifactRepository,
    DatasetRepository,
    ProvenanceRepository,
    RegistryRepository,
)
from trendsmapp.qc.coordinates import load_boundary
from trendsmapp.qc.models import QcReport
from trendsmapp.qc.pipeline import QcPipeline, QcResult
from trendsmapp.storage.paths import build_artifact_key
from trendsmapp.worker.handlers import JobExecutionContext, JobHandlerRegistry

__all__ = ["IngestWorkflow", "build_default_registry"]

#: Stage names recorded on the job row.
_STAGE_PARSE: Final[str] = "parse"
_STAGE_NORMALIZE: Final[str] = "normalize"
_STAGE_QC: Final[str] = "qc"
_STAGE_STORE: Final[str] = "store"
_STAGE_SEAL: Final[str] = "seal"

#: How many leading bytes a probe-only job reads.
_PROBE_BYTES: Final[int] = 64 * 1024


class IngestWorkflow:
    """Executes one ingest job end to end."""

    async def __call__(self, context: JobExecutionContext) -> dict[str, Any]:
        """Run the ingest pipeline described by the job payload.

        A job without a dataset version and mapping is the probe-only job
        enqueued at upload completion: it stores the parse-probe document so a
        client can poll for it. A job carrying a confirmed mapping and a
        dataset version runs the full pipeline and seals the version.
        """
        payload = context.payload
        upload_id = str(payload.get("upload_id", ""))
        raw_artifact_id = str(payload.get("raw_artifact_id", ""))
        version_id = str(payload.get("dataset_version_id", ""))
        mapping_dict = payload.get("mapping")
        if not raw_artifact_id:
            raise JobError(
                "The ingest job payload is missing the raw artifact.",
                details={"upload_id": upload_id},
            )
        if not version_id or not isinstance(mapping_dict, dict):
            return await self._probe_only(context, upload_id, raw_artifact_id, payload)
        mapping = ColumnMapping.model_validate(mapping_dict)

        await self._progress(context, 0.05, _STAGE_PARSE)
        with tempfile.TemporaryFile() as raw_spool:
            spool: BinaryIO = cast(BinaryIO, raw_spool)
            await self._spool_raw(context, raw_artifact_id, spool)
            spool.seek(0)
            session = ParseSession(
                spool,
                filename=str(payload.get("filename", "upload")),
                content_type=payload.get("content_type"),
                mapping=mapping,
                source_size_bytes=payload.get("size_bytes"),
                source_sha256=payload.get("sha256"),
                sheet=payload.get("sheet"),
                accept_cached_formula_values=(
                    context.settings.ingestion_accept_cached_formula_values
                ),
            )
            batches = list(session)
            parse_report = session.report
        if parse_report.failure is not None:
            raise JobError(
                "The upload could not be parsed under the confirmed mapping.",
                details={
                    "reason": "parse_failed",
                    "parse_failure": parse_report.failure.model_dump(mode="json"),
                },
            )

        await self._check_cancel(context)
        await self._progress(context, 0.25, _STAGE_NORMALIZE)
        dataset_id = str(payload.get("dataset_id", ""))
        normalization = NormalizationPipeline(
            mapping=mapping,
            dataset_id=dataset_id,
            dataset_version_id=version_id,
            decimal_style=DecimalStyle(parse_report.decimal_style),
            duplicate_policy=mapping.duplicate_policy,
        ).run(batches)

        await self._check_cancel(context)
        await self._progress(context, 0.55, _STAGE_QC)
        boundary = load_boundary()
        qc = QcPipeline(
            dataset_id=dataset_id,
            dataset_version_id=version_id,
            boundary=boundary,
        ).run(list(normalization.observations))

        await self._check_cancel(context)
        await self._progress(context, 0.75, _STAGE_STORE)
        artifacts = await self._store_artifacts(
            context,
            dataset_id,
            version_id,
            parse_report,
            normalization.report,
            qc.report,
            list(qc.observations),
        )

        await self._progress(context, 0.9, _STAGE_SEAL)
        stats = await self._register_and_seal(
            context,
            version_id=version_id,
            raw_artifact_id=raw_artifact_id,
            artifacts=artifacts,
            normalization=normalization,
            qc=qc,
            boundary_id=boundary.boundary_id,
        )
        await self._progress(context, 1.0, None)
        return {
            "dataset_version_id": version_id,
            "dataset_id": dataset_id,
            "upload_id": upload_id,
            "row_count": stats["row_count"],
            "observation_count": normalization.report.observation_count,
            "skipped_count": normalization.report.skipped_count,
            "qc": qc.report.to_summary_dict(),
            "artifacts": artifacts,
            "parse_report_sha256": artifacts["parse_report"]["sha256"],
        }

    async def _probe_only(
        self,
        context: JobExecutionContext,
        upload_id: str,
        raw_artifact_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Store the parse-probe document of a raw upload (no mapping yet)."""
        from trendsmapp.ingestion.parser import probe_parse

        await self._progress(context, 0.1, _STAGE_PARSE)
        with tempfile.TemporaryFile() as raw_spool:
            spool: BinaryIO = cast(BinaryIO, raw_spool)
            await self._spool_raw(context, raw_artifact_id, spool)
            spool.seek(0)
            head = spool.read(_PROBE_BYTES)
        probe = probe_parse(
            io.BytesIO(head),
            filename=str(payload.get("filename", "upload")),
            content_type=payload.get("content_type"),
        )
        document = {
            "schema_version": ARTIFACT_SCHEMA_VERSION,
            "kind": "probe",
            "upload_id": upload_id,
            "raw_artifact_id": raw_artifact_id,
            "filename": payload.get("filename"),
            "file_format": probe.file_type.format.value,
            "fields": list(probe.fields),
            "layout": probe.layout.value,
            "layout_confidence": probe.sniff.layout.confidence,
            "layout_evidence": list(probe.sniff.layout.evidence),
            "layout_warnings": list(probe.sniff.layout.warnings),
            "sniff_warnings": list(probe.sniff.warnings),
            "sheet_names": list(probe.sheet_names),
            "proposed_mapping": probe.proposed_mapping.model_dump(mode="json"),
            "proposal_warnings": list(probe.proposal_warnings),
        }
        blob = json.dumps(document, indent=2, sort_keys=True).encode("utf-8")
        digest = hashlib.sha256(blob).hexdigest()
        key = build_artifact_key("datasets", digest, "probe.json")
        stored = context.object_store.put_bytes(key, blob, content_type="application/json")
        artifact_id = new_artifact_id()
        async with session_scope(context.session_factory) as session:
            await ArtifactRepository(session).register(
                artifact_id=artifact_id,
                kind="parse_report",
                sha256=stored.sha256,
                size_bytes=stored.size_bytes,
                content_type=stored.content_type,
                storage_key=key,
                schema_version=ARTIFACT_SCHEMA_VERSION,
                metadata={"upload_id": upload_id, "probe": True},
            )
        await self._progress(context, 1.0, None)
        return {
            "stage": "probed",
            "upload_id": upload_id,
            "raw_artifact_id": raw_artifact_id,
            "probe_artifact_id": artifact_id,
            "layout": document["layout"],
            "fields": document["fields"],
        }

    async def _spool_raw(
        self, context: JobExecutionContext, artifact_id: str, spool: BinaryIO
    ) -> None:
        """Copy a stored raw artifact into a seekable local file."""
        async with session_scope(context.session_factory) as session:
            artifacts = ArtifactRepository(session)
            row = await artifacts.require(artifact_id)
            key = row.storage_key
        with context.object_store.open_stream(key) as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                spool.write(chunk)
        spool.flush()

    async def _store_artifacts(
        self,
        context: JobExecutionContext,
        dataset_id: str,
        version_id: str,
        parse_report: ParseReport,
        normalization_report: NormalizationReport,
        qc_report: QcReport,
        observations: list[Observation],
    ) -> dict[str, dict[str, Any]]:
        """Write every report and the canonical Parquet artifact to the store."""
        written: dict[str, dict[str, Any]] = {}

        def _put_json(name: str, kind: str, document: object) -> None:
            payload = json.dumps(document, indent=2, sort_keys=True, default=str).encode("utf-8")
            digest = hashlib.sha256(payload).hexdigest()
            key = build_artifact_key("datasets", digest, name)
            stored = context.object_store.put_bytes(key, payload, content_type="application/json")
            written[kind] = {
                "artifact_id": new_artifact_id(),
                "kind": kind,
                "sha256": stored.sha256,
                "size_bytes": stored.size_bytes,
                "storage_key": key,
                "content_type": stored.content_type,
            }

        _put_json("parse_report.json", "parse_report", parse_report.model_dump(mode="json"))
        _put_json(
            "normalization_report.json",
            "normalization_report",
            normalization_report.model_dump(mode="json"),
        )
        _put_json("qc_report.json", "qc_report", qc_report.model_dump(mode="json"))

        parquet_buffer = io.BytesIO()
        parquet = write_canonical_parquet(
            list(observations),
            parquet_buffer,
            dataset_id=dataset_id,
            dataset_version_id=version_id,
        )
        parquet_buffer.seek(0)
        key = build_artifact_key("datasets", parquet.sha256, "canonical.parquet")
        stored = context.object_store.put_stream(
            key, parquet_buffer, content_type="application/vnd.apache.parquet"
        )
        written["normalized_dataset"] = {
            "artifact_id": new_artifact_id(),
            "kind": "normalized_dataset",
            "sha256": stored.sha256,
            "size_bytes": stored.size_bytes,
            "storage_key": key,
            "content_type": stored.content_type,
            "row_count": parquet.row_count,
        }

        async with session_scope(context.session_factory) as session:
            artifacts = ArtifactRepository(session)
            for entry in written.values():
                await artifacts.register(
                    artifact_id=entry["artifact_id"],
                    kind=entry["kind"],
                    sha256=entry["sha256"],
                    size_bytes=entry["size_bytes"],
                    content_type=entry["content_type"],
                    storage_key=entry["storage_key"],
                    schema_version=ARTIFACT_SCHEMA_VERSION,
                    dataset_version_id=version_id,
                )
        return written

    async def _register_and_seal(
        self,
        context: JobExecutionContext,
        *,
        version_id: str,
        raw_artifact_id: str,
        artifacts: dict[str, dict[str, Any]],
        normalization: NormalizationResult,
        qc: QcResult,
        boundary_id: str,
    ) -> dict[str, Any]:
        """Register stations, parameters, and provenance; then seal the version."""
        observations = list(qc.observations)
        async with session_scope(context.session_factory) as session:
            datasets = DatasetRepository(session)
            registries = RegistryRepository(session)
            provenance = ProvenanceRepository(session)

            stations: dict[str, Any] = {}
            for observation in observations:
                stations.setdefault(
                    observation.station_id,
                    observation,
                )
            for station_id, observation in stations.items():
                await registries.add_station(
                    station_id=station_id,
                    dataset_version_id=version_id,
                    label=observation.station_label,
                    latitude_wgs84=observation.latitude_wgs84,
                    longitude_wgs84=observation.longitude_wgs84,
                    x_projected_m=observation.x_projected_m,
                    y_projected_m=observation.y_projected_m,
                    source_crs=observation.source_crs,
                    analysis_crs=observation.analysis_crs,
                    sector=observation.sector,
                    first_sampled_at=min(
                        (o.sampled_at for o in observations if o.station_id == station_id),
                        default=None,
                    ),
                    last_sampled_at=max(
                        (o.sampled_at for o in observations if o.station_id == station_id),
                        default=None,
                    ),
                )
            parameters: dict[str, Any] = {}
            for observation in observations:
                if observation.parameter_id:
                    parameters.setdefault(observation.parameter_id, observation)
            registry = get_parameter_registry()
            for parameter_id, observation in parameters.items():
                registered = registry.get(parameter_id)
                await registries.add_parameter(
                    parameter_id=parameter_id,
                    dataset_version_id=version_id,
                    label=observation.parameter_label,
                    canonical_unit=(
                        registered.canonical_unit
                        if registered is not None
                        else observation.canonical_unit
                    ),
                    dimension=registered.dimension if registered is not None else None,
                    display_name=registered.display_name if registered is not None else None,
                    aliases=list(registered.aliases) if registered is not None else [],
                )

            normalized = artifacts["normalized_dataset"]
            await provenance.record_event(
                event_type="ingest",
                dataset_version_id=version_id,
                input_artifact_ids=[raw_artifact_id],
                output_artifact_ids=[entry["artifact_id"] for entry in artifacts.values()],
                transformations=[
                    {"name": "parse", "detail": "format detection and long-schema conversion"},
                    {"name": "normalize", "detail": "canonical units, timestamps, coordinates"},
                    {"name": "qc", "detail": "quality-control flags"},
                ],
                details={
                    "upload_id": str(context.payload.get("upload_id", "")),
                    "mapping_schema_version": normalization.report.mapping.schema_version,
                    "boundary_id": boundary_id,
                },
            )
            sampled = [o.sampled_at for o in observations]
            await datasets.update_version_stats(
                version_id,
                row_count=normalization.report.observation_count,
                parameter_count=len(parameters),
                station_count=len(stations),
                first_sampled_at=min(sampled) if sampled else None,
                last_sampled_at=max(sampled) if sampled else None,
                normalized_artifact_id=normalized["artifact_id"],
                normalized_sha256=normalized["sha256"],
                boundary_id=boundary_id,
            )
            await datasets.seal_version(version_id)
        return {
            "row_count": normalization.report.observation_count,
            "parameter_count": len(parameters),
            "station_count": len(stations),
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


def build_default_registry() -> JobHandlerRegistry:
    """Build the workflow registry with every handler this build implements."""
    from trendsmapp.services.analysis import register_analysis_handlers
    from trendsmapp.services.animation import register_animate_handler

    registry = JobHandlerRegistry()
    registry.register(JobType.INGEST, IngestWorkflow())
    register_analysis_handlers(registry)
    register_animate_handler(registry)
    return registry
