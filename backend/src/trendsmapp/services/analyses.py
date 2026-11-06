"""The analysis application service: create runs and enqueue analysis jobs."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from trendsmapp.contracts.recipes import Recipe, recipe_hash
from trendsmapp.contracts.versions import APPLICATION_VERSION, ARTIFACT_SCHEMA_VERSION
from trendsmapp.domain.enums import JobType
from trendsmapp.domain.identifiers import new_job_id, new_run_id
from trendsmapp.errors import ConflictError, NotFoundError
from trendsmapp.geospatial.boundary import load_default_boundary
from trendsmapp.hashing import sha256_bytes
from trendsmapp.persistence.repositories import (
    ArtifactRepository,
    DatasetRepository,
    JobRepository,
    RunRepository,
)
from trendsmapp.settings import Settings
from trendsmapp.storage.base import ObjectStore

__all__ = ["AnalysisService", "CreateAnalysisResponse"]


class CreateAnalysisResponse:
    """The response of creating an analysis run."""

    def __init__(self, *, run_id: str, job_id: str, recipe_hash: str, status: str) -> None:
        self.run_id = run_id
        self.job_id = job_id
        self.recipe_hash = recipe_hash
        self.status = status

    def as_dict(self) -> dict[str, str]:
        """Return the JSON-able response."""
        return {
            "run_id": self.run_id,
            "job_id": self.job_id,
            "recipe_hash": self.recipe_hash,
            "status": self.status,
        }


class AnalysisService:
    """Coordinates recipe validation, run creation, and analysis jobs."""

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

    async def create(
        self, recipe: Recipe, *, idempotency_key: str | None = None
    ) -> CreateAnalysisResponse:
        """Validate the recipe against the dataset version and enqueue the analysis job.

        The dataset version must be sealed; an unsealed version has no immutable
        normalized artifact to analyze. The recipe hash is the idempotency key:
        the same recipe on the same version is never run twice.
        """
        version = await self._datasets.require_version(recipe.dataset_version_id)
        if version.sealed_at is None:
            raise ConflictError(
                "Only a sealed dataset version can be analyzed.",
                details={"dataset_version_id": recipe.dataset_version_id},
            )
        if version.normalized_artifact_id is None:
            raise ConflictError(
                "The dataset version has no normalized artifact.",
                details={"dataset_version_id": recipe.dataset_version_id},
            )
        digest = recipe_hash(recipe)

        # The recipe hash is the idempotency key: a repeated recipe on the same
        # version returns the existing run instead of enqueuing a second one.
        existing = await self._runs.find_by_recipe(version.id, digest)
        if existing is not None:
            return CreateAnalysisResponse(
                run_id=existing.id,
                job_id=existing.job_id or "",
                recipe_hash=digest,
                status=existing.status,
            )

        key = f"analyze:{digest}"

        run_id = new_run_id()
        boundary = load_default_boundary()
        run = await self._runs.create(
            run_id=run_id,
            dataset_version_id=version.id,
            recipe_hash=digest,
            recipe=recipe.model_dump(mode="json"),
            dataset_sha256=version.normalized_sha256 or "",
            boundary_sha256=boundary.sha256,
            seed=recipe.seed,
            application_version=APPLICATION_VERSION,
            schema_version=ARTIFACT_SCHEMA_VERSION,
        )
        job, _created = await self._jobs.create(
            job_type=JobType.ANALYZE,
            job_id=new_job_id(),
            payload={
                "run_id": run_id,
                "dataset_version_id": version.id,
                "recipe": recipe.model_dump(mode="json"),
                "recipe_hash": digest,
            },
            idempotency_key=key if idempotency_key is None else f"{key}:{idempotency_key}",
            request_hash=sha256_bytes(recipe.canonical_json().encode("utf-8")),
            run_id=run_id,
        )
        run.job_id = job.id
        await self._session.flush()
        return CreateAnalysisResponse(
            run_id=run_id, job_id=job.id, recipe_hash=digest, status=run.status
        )

    async def create_animation(
        self,
        run_id: str,
        request: Any,
        idempotency_key: str | None = None,
    ) -> dict[str, str]:
        """Enqueue an animation job over the stored rasters of a run."""
        run = await self._runs.require(run_id)
        if run.status != "succeeded":
            raise ConflictError(
                "Only a succeeded run can be animated.",
                details={"run_id": run_id, "status": run.status},
            )
        rasters = [
            row
            for row in await self._artifacts.list_for_run(run_id)
            if row.kind == "raster"
            and (row.details or {}).get("kind") == "geotiff"
            and (
                request.parameter_id is None
                or (row.details or {}).get("parameter_id") == request.parameter_id
            )
            and (request.method is None or (row.details or {}).get("method") == request.method)
        ]
        if not rasters:
            raise NotFoundError(
                "The run has no stored rasters for the requested parameter and method.",
                details={"run_id": run_id},
            )
        payload = {
            "run_id": run_id,
            "parameter_id": request.parameter_id,
            "method": request.method,
            "palette": request.palette,
            "fps": request.fps,
        }
        key = f"animate:{run_id}:" + sha256_bytes(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        )
        job, _created = await self._jobs.create(
            job_type=JobType.ANIMATE,
            job_id=new_job_id(),
            payload=payload,
            idempotency_key=key if idempotency_key is None else f"{key}:{idempotency_key}",
            request_hash=sha256_bytes(json.dumps(payload, sort_keys=True).encode("utf-8")),
            run_id=run_id,
        )
        return {"job_id": job.id, "run_id": run_id, "status": "accepted"}

    async def get_run(self, run_id: str) -> Any:
        """Return one run row."""
        return await self._runs.require(run_id)

    async def list_runs_for_version(self, dataset_version_id: str) -> list[Any]:
        """Return every run of a dataset version."""
        return await self._runs.list_for_version(dataset_version_id)

    async def list_artifacts(self, run_id: str) -> list[Any]:
        """Return every artifact produced by a run."""
        await self._runs.require(run_id)
        return await self._artifacts.list_for_run(run_id)

    async def report_artifact(self, run_id: str, kind: str) -> Any:
        """Return the report artifact of a run for a kind, when stored."""
        rows = await self._artifacts.list_for_run(run_id)
        artifact = next((row for row in rows if row.kind == kind), None)
        if artifact is None:
            raise NotFoundError(
                f"The run has no '{kind}' artifact yet.",
                details={"run_id": run_id, "kind": kind},
            )
        return artifact
