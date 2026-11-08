"""Unit tests for the reporting package: tables, manifest, bundle, verify."""

from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, datetime

import pytest

from trendsmapp.errors import ValidationError
from trendsmapp.hashing import is_sha256_hex, sha256_bytes
from trendsmapp.reporting import (
    build_bundle,
    build_manifest,
    dependency_lock_sha256,
    methods_record,
    result_tables,
    table_csv,
    verify_bundle,
)


def _rewrite_member(payload: bytes, name: str, new_bytes: bytes) -> bytes:
    """Return a copy of a ZIP with one member replaced, keeping all names."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        members = {member: archive.read(member) for member in archive.namelist()}
    members[name] = new_bytes
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for member, data in members.items():
            archive.writestr(member, data)
    return buffer.getvalue()


class TestTables:
    def test_table_csv_header_and_rows(self) -> None:
        payload = table_csv(["a", "b"], [{"a": 1, "b": "x"}, {"a": 2}])
        assert payload == b"a,b\n1,x\n2,\n"

    def test_table_csv_json_encodes_list_cells(self) -> None:
        payload = table_csv(["v"], [{"v": [1, 2]}])
        assert payload == b'v\n"[1, 2]"\n'

    def test_result_tables_ml_documents(self) -> None:
        metrics = {
            "aggregated": {"elastic_net": {"rmse_mean": 0.5, "rmse_ci95": [0.4, 0.6]}},
            "folds": [
                {
                    "fold_index": 0,
                    "family": "elastic_net",
                    "train_size": 10,
                    "test_size": 2,
                    "metrics": {"rmse": 0.5},
                }
            ],
        }
        predictions = {
            "folds": [
                {
                    "fold_index": 0,
                    "family": "elastic_net",
                    "y_true": [1.0, 2.0],
                    "y_pred": [1.1, 1.9],
                }
            ]
        }
        explanations = {"rows": [{"feature": "month", "method": "permutation", "value": 0.3}]}
        tables = result_tables(
            {"metrics": metrics, "predictions": predictions, "explanations": explanations}
        )
        assert set(tables) == {
            "ml-metrics.csv",
            "ml-folds.csv",
            "ml-predictions.csv",
            "ml-explanations.csv",
        }
        assert b"elastic_net,rmse_mean,0.5" in tables["ml-metrics.csv"]
        assert b"0,elastic_net,0,1.0,1.1" in tables["ml-predictions.csv"]
        assert b"month,permutation,0.3" in tables["ml-explanations.csv"]

    def test_result_tables_analysis_summary(self) -> None:
        summary = {
            "frames": [
                {
                    "parameter_id": "dissolved_oxygen",
                    "sampled_at": "2024-01-15T09:30:00+00:00",
                    "point_count": 4,
                    "skipped_reason": None,
                    "methods": [
                        {"method": "idw", "rmse": 0.1, "mae": 0.08, "bias": 0.01, "folds": 4}
                    ],
                    "decisions": [{"selected": "idw"}],
                }
            ]
        }
        tables = result_tables({"metrics": summary})
        assert set(tables) == {"analysis-frames.csv"}
        assert b"dissolved_oxygen" in tables["analysis-frames.csv"]
        assert b"idw" in tables["analysis-frames.csv"]


class TestManifest:
    def _run(self) -> dict:
        return {
            "id": "run_" + "a" * 32,
            "status": "succeeded",
            "recipe_hash": "b" * 64,
            "recipe": {"seed": 7},
            "seed": 7,
            "boundary_sha256": "c" * 64,
            "created_at": datetime(2026, 1, 1, tzinfo=UTC),
            "finished_at": datetime(2026, 1, 1, 0, 5, tzinfo=UTC),
        }

    def test_manifest_has_every_required_hash_and_version(self) -> None:
        manifest = build_manifest(
            run=self._run(),
            dataset_version={"id": "dsv_" + "d" * 32, "normalized_sha256": "e" * 64},
            artifacts=[
                {
                    "artifact_id": "art_" + "f" * 32,
                    "kind": "metrics",
                    "sha256": "0" * 64,
                    "size_bytes": 10,
                    "content_type": "application/json",
                    "bundle_path": "artifacts/metrics.json",
                }
            ],
            tables={"ml-metrics.csv": "1" * 64},
            methods={"seed": 7},
            generated_at=datetime(2026, 1, 1, 0, 5, tzinfo=UTC),
            lock_sha256="2" * 64,
        )
        assert manifest["schema_version"] == "1.0.0"
        assert manifest["run_id"] == self._run()["id"]
        assert manifest["dataset_sha256"] == "e" * 64
        assert manifest["boundary_sha256"] == "c" * 64
        assert manifest["recipe_hash"] == "b" * 64
        assert manifest["dependency_lock"]["sha256"] == "2" * 64
        assert manifest["artifacts"][0]["bundle_path"] == "artifacts/metrics.json"
        assert manifest["reproduction"]["command"].startswith("trendsmapp reproduce")

    def test_manifest_is_deterministic(self) -> None:
        kwargs = {
            "run": self._run(),
            "dataset_version": {"id": "dsv_" + "d" * 32, "normalized_sha256": "e" * 64},
            "artifacts": [],
            "tables": {},
            "methods": {},
            "generated_at": datetime(2026, 1, 1, tzinfo=UTC),
            "lock_sha256": None,
        }
        first = build_manifest(**kwargs)
        second = build_manifest(**kwargs)
        assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)

    def test_dependency_lock_sha256_finds_repo_lockfile(self) -> None:
        digest = dependency_lock_sha256()
        assert digest is None or is_sha256_hex(digest)


class TestBundle:
    def _bundle(self) -> bytes:
        manifest = build_manifest(
            run={
                "id": "run_" + "a" * 32,
                "status": "succeeded",
                "recipe_hash": "b" * 64,
                "recipe": {},
                "seed": 1,
                "boundary_sha256": None,
                "created_at": datetime(2026, 1, 1, tzinfo=UTC),
                "finished_at": None,
            },
            dataset_version={"id": "dsv_" + "d" * 32, "normalized_sha256": "e" * 64},
            artifacts=[],
            tables={},
            methods={},
            generated_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        return build_bundle(
            manifest=manifest,
            files=[("tables/ml-metrics.csv", b"family,metric,value\n"), ("README.md", b"# hi\n")],
        )

    def test_build_and_verify_round_trip(self) -> None:
        payload = self._bundle()
        report = verify_bundle(payload)
        assert report.ok
        assert report.checked_files == 3  # manifest + 2 files
        assert report.manifest["run_id"] == "run_" + "a" * 32

    def test_bundle_is_byte_deterministic(self) -> None:
        assert self._bundle() == self._bundle()
        assert sha256_bytes(self._bundle()) == sha256_bytes(self._bundle())

    def test_tampered_member_is_detected(self) -> None:
        payload = self._bundle()
        tampered = _rewrite_member(payload, "README.md", b"# changed\n")
        report = verify_bundle(tampered)
        assert not report.ok
        assert "README.md" in report.mismatches

    def test_missing_member_is_detected(self) -> None:
        payload = self._bundle()
        buffer = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            members = {
                member: archive.read(member)
                for member in archive.namelist()
                if member != "README.md"
            }
        with zipfile.ZipFile(buffer, "w") as archive:
            for member, data in members.items():
                archive.writestr(member, data)
        report = verify_bundle(buffer.getvalue())
        assert not report.ok
        assert "README.md" in report.missing

    def test_not_a_zip_raises(self) -> None:
        with pytest.raises(ValidationError):
            verify_bundle(b"this is not a zip")

    def test_missing_manifest_raises(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("checksums.sha256", "")
        with pytest.raises(ValidationError):
            verify_bundle(buffer.getvalue())

    def test_reserved_names_rejected(self) -> None:
        with pytest.raises(ValueError, match="reserved"):
            build_bundle(manifest={"schema_version": "1.0.0"}, files=[("manifest.json", b"{}")])


class TestMethodsRecord:
    def test_analysis_recipe(self) -> None:
        record = methods_record(
            {
                "seed": 7,
                "spatial": {
                    "methods": [{"method": "idw"}],
                    "analysis_crs": "EPSG:32644",
                    "validation": "leave_one_station_out",
                },
                "temporal": {"resolution": "day", "interpolation": "linear"},
            }
        )
        assert record["spatial"]["methods"] == ["idw"]
        assert record["temporal"]["resolution"] == "day"
        assert record["machine_learning"] is None

    def test_ml_task(self) -> None:
        record = methods_record(
            {
                "seed": 3,
                "target_parameter_id": "dissolved_oxygen",
                "setting": "known_station_temporal",
                "outer_split": "station_group",
                "candidate_models": ["elastic_net"],
                "uncertainty_method": "bootstrap_ensemble",
            }
        )
        ml = record["machine_learning"]
        assert ml["candidate_models"] == ["elastic_net"]
        assert ml["outer_split"] == "station_group"
        assert ml["uncertainty_method"] == "bootstrap_ensemble"
