"""Model training: the service that starts a run and the worker job that finishes it.

The service validates the task against a sealed dataset version and enqueues a
``train`` job; the workflow reads the sealed version, builds the feature frame,
runs the outer/inner evaluation, computes uncertainty and explanations on the
held-out rows, and stores the model package, the results, and the explanations
as artifacts of the run.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from trendsmapp.contracts.tasks import MLTask, task_hash
from trendsmapp.contracts.versions import APPLICATION_VERSION, ARTIFACT_SCHEMA_VERSION
from trendsmapp.domain.enums import ExplanationMethod, JobType
from trendsmapp.domain.identifiers import new_artifact_id, new_job_id, new_run_id
from trendsmapp.errors import ConflictError, JobError, NotFoundError
from trendsmapp.explainability.pipeline import explain_model
from trendsmapp.ml.artifacts import save_model
from trendsmapp.ml.pipeline import FeatureFrame, build_feature_frame, uncertainty_for_selected
from trendsmapp.ml.training import TrainingResult, train_and_evaluate
from trendsmapp.ml.uncertainty import UncertaintyResult
from trendsmapp.normalization.pipeline import observations_from_parquet
from trendsmapp.persistence.database import session_scope
from trendsmapp.persistence.repositories import (
    ArtifactRepository,
    DatasetRepository,
    JobRepository,
    RunRepository,
)
from trendsmapp.settings import Settings
from trendsmapp.storage.base import ObjectStore
from trendsmapp.storage.paths import build_artifact_key
from trendsmapp.worker.handlers import JobExecutionContext, JobHandlerRegistry

__all__ = ["ModelService", "TrainWorkflow", "register_model_handler"]

_STAGE_LOAD: Final[str] = "load"
_STAGE_TRAIN: Final[str] = "train"
_STAGE_EXPLAIN: Final[str] = "explain"
_STAGE_STORE: Final[str] = "store"


class ModelService:
    """Creates model runs and reads their results."""

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
        self._datasets = DatasetRepository(session)
        self._jobs = JobRepository(session)
        self._artifacts = ArtifactRepository(session)

    async def create(self, task: MLTask) -> dict[str, str]:
        """Validate the task and enqueue the training job."""
        version = await self._datasets.require_version(task.dataset_version_id)
        if version.sealed_at is None:
            raise ConflictError(
                "Only a sealed dataset version can be trained on.",
                details={"dataset_version_id": task.dataset_version_id},
            )
        if version.normalized_artifact_id is None:
            raise ConflictError(
                "The dataset version has no normalized artifact.",
                details={"dataset_version_id": task.dataset_version_id},
            )
        digest = task_hash(task)
        existing = await self._runs.find_by_recipe(version.id, digest)
        if existing is not None:
            job_id = existing.job_id
            if job_id is None:
                job = await self._jobs.find_by_idempotency_key(f"train:{digest}")
                job_id = job.id if job is not None else ""
            return {
                "run_id": existing.id,
                "job_id": job_id or "",
                "task_hash": digest,
                "status": existing.status,
            }
        run_id = new_run_id()
        await self._runs.create(
            run_id=run_id,
            dataset_version_id=version.id,
            recipe_hash=digest,
            recipe=task.model_dump(mode="json"),
            dataset_sha256=version.normalized_sha256 or "",
            boundary_sha256=None,
            seed=task.seed,
            application_version=APPLICATION_VERSION,
            schema_version=ARTIFACT_SCHEMA_VERSION,
        )
        job, _created = await self._jobs.create(
            job_type=JobType.TRAIN,
            job_id=new_job_id(),
            payload={
                "run_id": run_id,
                "dataset_version_id": version.id,
                "task": task.model_dump(mode="json"),
                "task_hash": digest,
            },
            idempotency_key=f"train:{digest}",
            request_hash=hashlib.sha256(digest.encode("utf-8")).hexdigest(),
            run_id=run_id,
            dataset_version_id=version.id,
        )
        await self._runs.attach_job(run_id, job.id)
        return {
            "run_id": run_id,
            "job_id": job.id,
            "task_hash": digest,
            "status": "accepted",
        }

    async def get_run(self, run_id: str) -> Any:
        """Return one model run row."""
        return await self._runs.require(run_id)

    async def list_artifacts(self, run_id: str) -> list[Any]:
        """Return every artifact a model run produced."""
        await self._runs.require(run_id)
        return await self._artifacts.list_for_run(run_id)

    async def artifact_document(self, run_id: str, kind: str) -> dict[str, Any]:
        """Return one stored JSON artifact document of a run."""
        rows = await self._artifacts.list_for_run(run_id)
        artifact = next((row for row in rows if row.kind == kind), None)
        if artifact is None:
            raise NotFoundError(
                f"The run has no '{kind}' artifact.",
                details={"run_id": run_id, "kind": kind},
            )
        payload = self._store.get_bytes(artifact.storage_key)
        document: dict[str, Any] = json.loads(payload.decode("utf-8"))
        return document


class TrainWorkflow:
    """Executes one ``train`` job end to end."""

    async def __call__(self, context: JobExecutionContext) -> dict[str, Any]:
        """Train, evaluate, explain, and store the artifacts of one model run."""
        payload = context.payload
        run_id = str(payload.get("run_id", ""))
        task_dict = payload.get("task")
        if not run_id or not isinstance(task_dict, dict):
            raise JobError(
                "The train job payload is missing the run or the task.",
                details={"has_run": bool(run_id), "has_task": isinstance(task_dict, dict)},
            )
        task = MLTask.model_validate(task_dict)

        await self._progress(context, 0.05, _STAGE_LOAD)
        observations = await self._load_observations(context, task.dataset_version_id)

        await self._check_cancel(context)
        await self._progress(context, 0.2, _STAGE_TRAIN)
        frame = build_feature_frame(observations, task)
        training = train_and_evaluate(
            task,
            x=frame.x,
            y=frame.y,
            groups=frame.groups,
            years=frame.years,
            sectors=frame.sectors,
            coords_m=frame.coords_m,
            feature_names=frame.feature_names,
            feature_table_sha256=frame.sha256,
            task_hash=task_hash(task),
            save_model=save_model,
        )

        await self._check_cancel(context)
        await self._progress(context, 0.55, "uncertainty")
        uncertainty = uncertainty_for_selected(task, frame, training)

        await self._check_cancel(context)
        await self._progress(context, 0.6, _STAGE_EXPLAIN)
        explanations = self._explain(task, training, frame)

        await self._progress(context, 0.8, _STAGE_STORE)
        stored = await self._store_artifacts(
            context, task, frame, training, uncertainty, explanations, run_id
        )

        async with session_scope(context.session_factory) as session:
            await RunRepository(session).finish(run_id, status="succeeded")
        await self._progress(context, 1.0, None)
        return {
            "run_id": run_id,
            "dataset_version_id": task.dataset_version_id,
            "selected_family": training.selected_family.value,
            "observation_count": len(observations),
            "rows": len(frame.y),
            "folds": len({fold.fold_index for fold in training.folds}),
            "uncertainty": {
                "method": uncertainty.method.value,
                "empirical_coverage": uncertainty.empirical_coverage,
            },
            "artifacts": stored,
            "warnings": list(training.warnings)
            + list(uncertainty.notes)
            + list(explanations.get("limitations", [])),
        }

    async def _load_observations(self, context: JobExecutionContext, version_id: str) -> list[Any]:
        """Read the sealed dataset version's normalized artifact."""
        async with session_scope(context.session_factory) as session:
            datasets = DatasetRepository(session)
            artifacts = ArtifactRepository(session)
            version = await datasets.require_version(version_id)
            if version.normalized_artifact_id is None:
                raise JobError(
                    "The dataset version has no normalized artifact.",
                    details={"dataset_version_id": version_id},
                )
            artifact = await artifacts.require(version.normalized_artifact_id)
            key = artifact.storage_key
        with context.object_store.open_stream(key) as handle:
            return observations_from_parquet(handle)

    def _explain(
        self, task: MLTask, training: TrainingResult, frame: FeatureFrame
    ) -> dict[str, Any]:
        """Explain the selected model on the held-out rows."""
        methods = tuple(task.explanation_methods) or (ExplanationMethod.PERMUTATION,)
        held_out_index: list[int] = []
        for fold in training.folds:
            if fold.family is training.selected_family:
                held_out_index.extend(fold.test_index)
        if not held_out_index:
            held_out_index = list(range(len(frame.y)))
        estimator = getattr(training.final_model, "estimator", None)
        table = explain_model(
            family=training.selected_family,
            predict=lambda values: training.final_model.predict(values),
            x=frame.x[held_out_index],
            y=frame.y[held_out_index],
            feature_names=frame.feature_names,
            methods=methods,
            estimator=estimator,
            seed=task.seed,
            primary_metric=task.primary_metric,
        )
        document = table.as_payload()
        document["held_out_rows"] = len(held_out_index)
        return document

    async def _store_artifacts(
        self,
        context: JobExecutionContext,
        task: MLTask,
        frame: FeatureFrame,
        training: TrainingResult,
        uncertainty: UncertaintyResult,
        explanations: dict[str, Any],
        run_id: str,
    ) -> list[str]:
        """Store the model package, the results, the predictions, and the explanations."""
        digest = task_hash(task)
        entries: list[tuple[str, str, bytes, str, dict[str, Any]]] = []
        document_meta = {
            "schema_version": ARTIFACT_SCHEMA_VERSION,
            "application_version": APPLICATION_VERSION,
            "run_id": run_id,
            "task_hash": digest,
        }

        model_bytes = save_model(
            training.final_model,
            training.final_preprocessor,
            list(training.feature_names),
            task,
        )
        entries.append(
            (
                "model",
                f"model-{digest[:12]}.pkg",
                model_bytes,
                "application/octet-stream",
                {
                    "task_hash": digest,
                    "family": training.selected_family.value,
                    "feature_table_sha256": training.feature_table_sha256,
                },
            )
        )
        results = {
            **document_meta,
            "task": task.model_dump(mode="json"),
            "feature_names": list(training.feature_names),
            "feature_table_sha256": training.feature_table_sha256,
            "rows": len(frame.y),
            "aggregated": training.aggregated,
            "baseline_comparison": training.baseline_comparison,
            "selected_family": training.selected_family.value,
            "selected_params": training.selected_params,
            "final_model_sha256": training.final_model_sha256,
            "uncertainty": {
                "method": uncertainty.method.value,
                "empirical_coverage": uncertainty.empirical_coverage,
                "notes": list(uncertainty.notes),
            },
            "folds": [
                {
                    "fold_index": fold.fold_index,
                    "family": fold.family.value,
                    "train_size": fold.train_size,
                    "test_size": fold.test_size,
                    "metrics": fold.metrics,
                }
                for fold in training.folds
            ],
            "warnings": list(training.warnings) + list(uncertainty.notes),
        }
        entries.append(
            (
                "metrics",
                f"ml-results-{digest[:12]}.json",
                json.dumps(results, indent=2, sort_keys=True, default=str).encode("utf-8"),
                "application/json",
                {"task_hash": digest},
            )
        )
        predictions = {
            **document_meta,
            "feature_names": list(frame.feature_names),
            "feature_table_sha256": frame.sha256,
            "folds": [
                {
                    "fold_index": fold.fold_index,
                    "family": fold.family.value,
                    "test_size": fold.test_size,
                    "y_true": [float(value) for value in fold.y_true],
                    "y_pred": [float(value) for value in fold.y_pred],
                }
                for fold in training.folds
            ],
        }
        entries.append(
            (
                "predictions",
                f"ml-predictions-{digest[:12]}.json",
                json.dumps(predictions, indent=2, sort_keys=True, default=str).encode("utf-8"),
                "application/json",
                {"task_hash": digest},
            )
        )
        explanations_document = {
            **document_meta,
            **explanations,
        }
        entries.append(
            (
                "explanations",
                f"ml-explanations-{digest[:12]}.json",
                json.dumps(explanations_document, indent=2, sort_keys=True, default=str).encode(
                    "utf-8"
                ),
                "application/json",
                {"task_hash": digest},
            )
        )

        artifact_ids: list[str] = []
        async with session_scope(context.session_factory) as session:
            artifacts = ArtifactRepository(session)
            for kind, name, payload_bytes, content_type, metadata in entries:
                payload_digest = hashlib.sha256(payload_bytes).hexdigest()
                key = build_artifact_key("runs", payload_digest, name)
                context.object_store.put_bytes(key, payload_bytes, content_type=content_type)
                registered = await artifacts.register(
                    artifact_id=new_artifact_id(),
                    kind=kind,
                    sha256=payload_digest,
                    size_bytes=len(payload_bytes),
                    content_type=content_type,
                    storage_key=key,
                    schema_version=ARTIFACT_SCHEMA_VERSION,
                    dataset_version_id=metadata.get("dataset_version_id"),
                    run_id=run_id,
                    metadata=metadata,
                )
                artifact_ids.append(registered.id)
        return artifact_ids

    async def _progress(
        self, context: JobExecutionContext, progress: float, stage: str | None
    ) -> None:
        """Record job progress and heartbeat in one call."""
        await context.heartbeat.record_progress(context.job_id, progress=progress, stage=stage)

    async def _check_cancel(self, context: JobExecutionContext) -> None:
        """Raise when cancellation was requested for the job."""
        if await context.cancellation_probe():
            raise JobError("The job was cancelled.", details={"reason": "cancelled"})


def register_model_handler(registry: JobHandlerRegistry) -> None:
    """Register the model training handler on a workflow registry."""
    registry.register(JobType.TRAIN, TrainWorkflow())
