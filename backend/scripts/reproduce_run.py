"""Re-execute an exported run from its bundle and compare the results.

Usage::

    python scripts/reproduce_run.py --bundle export.zip \
        --database-url sqlite+aiosqlite:///path/to/app.db \
        --storage-root path/to/objects [--tolerance 1e-9]

The script verifies every checksum in the bundle, checks that the manifest's
dataset version exists with the recorded dataset hash, re-executes the run's
recipe through the public in-process workflows, and compares every stored
metric against the recomputed one within the relative tolerance. It prints a
JSON report and exits non-zero on any mismatch, so it works as a CI
reproduction gate.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import sys
import zipfile
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from trendsmapp.contracts.recipes import Recipe
from trendsmapp.contracts.tasks import MLTask
from trendsmapp.geospatial.boundary import load_default_boundary
from trendsmapp.normalization.pipeline import observations_from_parquet
from trendsmapp.persistence.repositories import ArtifactRepository, DatasetRepository
from trendsmapp.reporting.verify import verify_bundle
from trendsmapp.spatial.pipeline import run_spatial_analysis
from trendsmapp.storage.local import LocalObjectStore
from trendsmapp.temporal.pipeline import run_temporal_analysis


def _compare_numbers(
    expected: Any,
    actual: Any,
    tolerance: float,
    path: str,
    mismatches: list[str],
    checked: list[str],
) -> None:
    """Compare one numeric (or list of numerics) within the relative tolerance."""
    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            mismatches.append(f"{path}: length {len(expected)} != {len(actual)}")
            return
        for index, (left, right) in enumerate(zip(expected, actual, strict=True)):
            _compare_numbers(left, right, tolerance, f"{path}[{index}]", mismatches, checked)
        return
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        checked.append(path)
        if abs(float(expected) - float(actual)) > tolerance * max(1.0, abs(float(expected))):
            mismatches.append(f"{path}: stored {expected} != recomputed {actual}")
        return
    if expected != actual:
        mismatches.append(f"{path}: stored {expected!r} != recomputed {actual!r}")


def _read_bundle_document(payload: bytes, bundle_path: str) -> dict[str, Any]:
    """Read one JSON member of the bundle."""
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        document = json.loads(archive.read(bundle_path).decode("utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{bundle_path} must contain a mapping.")
    return document


async def reproduce(
    *,
    bundle_path: Path,
    database_url: str,
    storage_root: Path,
    tolerance: float = 1e-9,
) -> dict[str, Any]:
    """Verify the bundle, re-execute the run, and compare the metrics."""
    payload = await asyncio.to_thread(bundle_path.read_bytes)
    verification = verify_bundle(payload)
    if not verification.ok:
        return {
            "ok": False,
            "stage": "bundle-verification",
            "mismatches": list(verification.mismatches),
            "missing": list(verification.missing),
        }
    manifest = verification.manifest
    run_id = str(manifest.get("run_id"))
    recipe_document = manifest.get("recipe")
    if not isinstance(recipe_document, dict):
        return {"ok": False, "stage": "manifest", "mismatches": ["manifest has no recipe"]}

    engine = create_async_engine(database_url)
    try:
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            datasets = DatasetRepository(session)
            artifacts = ArtifactRepository(session)
            version = await datasets.get_version(str(manifest.get("dataset_version_id")))
            if version is None:
                return {
                    "ok": False,
                    "stage": "dataset",
                    "mismatches": [
                        f"dataset version {manifest.get('dataset_version_id')} not found"
                    ],
                }
            if version.normalized_sha256 != manifest.get("dataset_sha256"):
                return {
                    "ok": False,
                    "stage": "dataset",
                    "mismatches": ["dataset hash differs from the manifest"],
                }
            if version.normalized_artifact_id is None:
                return {
                    "ok": False,
                    "stage": "dataset",
                    "mismatches": ["version has no normalized artifact"],
                }
            artifact = await artifacts.require(version.normalized_artifact_id)
        store = LocalObjectStore(storage_root)
        with store.open_stream(artifact.storage_key) as handle:
            observations = observations_from_parquet(handle)
    finally:
        await engine.dispose()

    # The stored metrics document inside the bundle.
    metrics_entry = next(
        (entry for entry in manifest.get("artifacts", []) if entry.get("kind") == "metrics"),
        None,
    )
    if metrics_entry is None:
        return {"ok": False, "stage": "manifest", "mismatches": ["bundle has no metrics artifact"]}
    stored_metrics = _read_bundle_document(payload, str(metrics_entry["bundle_path"]))

    mismatches: list[str] = []
    checked: list[str] = []
    if "candidate_models" in recipe_document:
        task = MLTask.model_validate(recipe_document)
        from trendsmapp.ml.pipeline import run_ml_task

        result = run_ml_task(task, observations)
        stored_aggregated = stored_metrics.get("aggregated")
        if not isinstance(stored_aggregated, dict):
            mismatches.append("bundle metrics document has no aggregated table")
        else:
            for family, metrics in result.training.aggregated.items():
                stored_family = stored_aggregated.get(family)
                if not isinstance(stored_family, dict):
                    mismatches.append(f"aggregated[{family}]: missing in bundle")
                    continue
                for metric, value in metrics.items():
                    _compare_numbers(
                        stored_family.get(metric),
                        value,
                        tolerance,
                        f"aggregated.{family}.{metric}",
                        mismatches,
                        checked,
                    )
    else:
        recipe = Recipe.model_validate(recipe_document)
        boundary = load_default_boundary()
        spatial_result = run_spatial_analysis(
            observations=observations,
            recipe=recipe.spatial.to_spatial_recipe(),
            boundary=boundary,
            sink=lambda kind, name, payload_bytes, content_type, metadata: f"reproduce/{name}",
        )
        if recipe.temporal is not None:
            run_temporal_analysis(
                observations=observations,
                recipe=recipe.temporal.to_temporal_recipe(seed=recipe.seed),
            )
        stored_frames = stored_metrics.get("frames")
        if not isinstance(stored_frames, list):
            mismatches.append("bundle metrics document has no frames table")
        else:
            for index, frame in enumerate(spatial_result.frames):
                stored_frame = stored_frames[index] if index < len(stored_frames) else None
                if not isinstance(stored_frame, dict):
                    mismatches.append(f"frames[{index}]: missing in bundle")
                    continue
                stored_methods = stored_frame.get("methods")
                if not isinstance(stored_methods, list):
                    continue
                for method in frame.methods:
                    stored_method = next(
                        (
                            m
                            for m in stored_methods
                            if isinstance(m, dict) and m.get("method") == method.method.value
                        ),
                        None,
                    )
                    if stored_method is None:
                        mismatches.append(
                            f"frames[{index}].{method.method.value}: missing in bundle"
                        )
                        continue
                    for metric_name in ("rmse", "mae", "bias"):
                        stored_value = stored_method.get(metric_name)
                        actual_value = (
                            getattr(method.metrics, metric_name)
                            if method.metrics is not None
                            else None
                        )
                        if stored_value is None and actual_value is None:
                            continue
                        _compare_numbers(
                            stored_value,
                            actual_value,
                            tolerance,
                            f"frames[{index}].{method.method.value}.{metric_name}",
                            mismatches,
                            checked,
                        )

    return {
        "ok": not mismatches,
        "stage": "comparison",
        "run_id": run_id,
        "checked_metrics": len(checked),
        "mismatches": mismatches,
        "tolerance": tolerance,
    }


def main(argv: list[str] | None = None) -> int:
    """Run the reproduction and return a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True, help="The export bundle ZIP.")
    parser.add_argument(
        "--database-url",
        default="sqlite+aiosqlite:///./trendsmapp.db",
        help="Database URL of the deployment that owns the run.",
    )
    parser.add_argument(
        "--storage-root",
        type=Path,
        default=Path("./var/objects"),
        help="Root of the local object store.",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=1e-9,
        help="Relative tolerance for numeric metric comparison.",
    )
    args = parser.parse_args(argv)
    report = asyncio.run(
        reproduce(
            bundle_path=args.bundle,
            database_url=args.database_url,
            storage_root=args.storage_root,
            tolerance=args.tolerance,
        )
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
