"""Unit tests for the PDF report builder."""

from __future__ import annotations

import pytest

from trendsmapp.reporting import build_report_pdf


def _png_bytes() -> bytes:
    """A tiny valid 8x8 red PNG."""
    import zlib

    def chunk(tag: bytes, data: bytes) -> bytes:
        return len(data).to_bytes(4, "big") + tag + data + zlib.crc32(tag + data).to_bytes(4, "big")

    header = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", (8).to_bytes(4, "big") + (8).to_bytes(4, "big") + bytes([8, 2, 0, 0, 0]))
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * 8 for _ in range(8))
    idat = chunk(b"IDAT", zlib.compress(raw))
    iend = chunk(b"IEND", b"")
    return header + ihdr + idat + iend


def _manifest() -> dict:
    return {
        "schema_version": "1.0.0",
        "application_version": "0.1.0",
        "run_id": "run_" + "a" * 32,
        "dataset_sha256": "b" * 64,
        "boundary_sha256": "c" * 64,
        "recipe_hash": "d" * 64,
        "seed": 7,
        "generated_at": "2026-11-12T10:00:00+00:00",
        "methods": {
            "spatial": {
                "methods": ["idw"],
                "analysis_crs": "EPSG:32644",
                "grid_resolution_m": 5000.0,
                "validation": "leave_one_station_out",
            },
            "machine_learning": {
                "setting": "known_station_temporal",
                "outer_split": "station_group",
                "inner_split": "station_group",
                "candidate_models": ["elastic_net"],
                "search_budget": 1,
                "uncertainty_method": "quantile",
                "explanation_methods": ["permutation"],
            },
        },
        "reproduction": {"command": "trendsmapp reproduce <bundle.zip>"},
        "artifacts": [
            {
                "artifact_id": "art_" + "e" * 32,
                "kind": "metrics",
                "sha256": "f" * 64,
                "size_bytes": 100,
                "content_type": "application/json",
                "bundle_path": "artifacts/metrics.json",
            }
        ],
    }


def _metrics_doc() -> dict:
    return {
        "aggregated": {
            "elastic_net": {"rmse_mean": 0.42, "rmse_ci95": [0.4, 0.44], "mae_mean": 0.3},
            "mean_baseline": {"rmse_mean": 0.9, "rmse_ci95": [0.8, 1.0], "mae_mean": 0.7},
        },
        "baseline_comparison": {"mean_baseline": {}},
        "selected_family": "elastic_net",
        "uncertainty": {"method": "quantile", "empirical_coverage": 0.95},
        "folds": [
            {
                "fold_index": 0,
                "family": "elastic_net",
                "train_size": 20,
                "test_size": 4,
                "metrics": {"rmse": 0.42},
            }
        ],
    }


def test_build_report_pdf_is_a_valid_pdf_with_all_sections() -> None:
    pdf = build_report_pdf(
        manifest=_manifest(),
        documents={
            "metrics": _metrics_doc(),
            "predictions": {
                "folds": [
                    {
                        "fold_index": 0,
                        "family": "elastic_net",
                        "test_size": 2,
                        "y_true": [6.5, 6.6],
                        "y_pred": [6.4, 6.7],
                    }
                ]
            },
            "explanations": {"rows": [{"feature": "month", "method": "permutation", "value": 0.3}]},
        },
        tables={"ml-metrics.csv": b"family,metric,value\nelastic_net,rmse_mean,0.42\n"},
        figures=[("raster abc", _png_bytes())],
    )
    assert pdf.startswith(b"%PDF-")
    assert pdf.rstrip().endswith(b"%%EOF")
    assert len(pdf) > 10_000  # cover + methods + tables + figure + ML charts + appendix


def test_build_report_pdf_is_deterministic() -> None:
    kwargs = {
        "manifest": _manifest(),
        "documents": {"metrics": _metrics_doc()},
        "tables": {"ml-metrics.csv": b"family,metric,value\nelastic_net,rmse_mean,0.42\n"},
        "figures": [],
    }
    first = build_report_pdf(**kwargs)
    second = build_report_pdf(**kwargs)
    assert first == second


def test_build_report_pdf_without_ml_section() -> None:
    manifest = _manifest()
    manifest["methods"] = {"spatial": {"methods": ["idw"]}}
    pdf = build_report_pdf(
        manifest=manifest,
        documents={
            "metrics": {
                "frames": [
                    {
                        "parameter_id": "dissolved_oxygen",
                        "methods": [{"method": "idw", "rmse": 0.1}],
                    }
                ]
            }
        },
        tables={"analysis-frames.csv": b"parameter_id,method,rmse\ndissolved_oxygen,idw,0.1\n"},
        figures=[],
    )
    assert pdf.startswith(b"%PDF-")


def test_build_report_pdf_rejects_unknown_chart_kind() -> None:
    from trendsmapp.reporting.report import _matplotlib_chart

    with pytest.raises(ValueError, match="unknown chart kind"):
        _matplotlib_chart("nope", {})


def test_png_figure_scales_down() -> None:
    from trendsmapp.reporting.report import _png_figure

    image = _png_figure(_png_bytes())
    assert image.drawWidth <= 15 * 72  # capped at 15cm in points
