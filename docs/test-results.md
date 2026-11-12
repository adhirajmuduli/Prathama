# Test run results

Latest full backend run: see the summary below (regenerate with
`cd backend && .venv/Scripts/python.exe -m pytest -v --cov --cov-report=term`).

<!-- BEGIN-GENERATED -->
## Latest full run (backend, `pytest -v --cov`)

- **Result: 850 passed, 0 failed** in ? (exit code 0).
- **Coverage: 90.35%** (gate: 90%).
- Date of run: 2026-11-12, Python 3.13, pytest 9.2.
- Includes the new report feature: `test_report_pdf.py` (5 tests: valid PDF,
  byte-determinism, analysis-only reports, chart-kind validation, figure
  scaling) and `test_api_reports.py` (3 tests: worker registration, full
  report E2E with PDF download + SHA-256 header, 404/409 paths).

<!-- END-GENERATED -->

## What the suite covers

| Area | Test files | What they prove |
| --- | --- | --- |
| Ingestion (CSV/TSV/XLSX/Parquet, sniffing, chunking, security limits) | `test_ingestion_*.py` | Magic-byte checks, decompression-ratio and zip-slip rejection, exact-text cell emission, formula/error-cell policies, fixture digests. |
| Normalization (timestamps, coordinates, units, values, canonicalization) | `test_normalization_*.py` | Timezone policies, CRS transforms, unit conversion chains, QC flag semantics (flag, never delete). |
| QC pipeline and rules | `test_qc_*.py` | Ranges, detection limits, outliers, temporal gaps, boundary containment, drift; report JSON round-trips; determinism. |
| Spatial methods and pipeline | `test_spatial_*.py` | IDW/RBF/kriging/GP, raster GeoTIFF/PNG round-trips with CRS+nodata, grid/cell/timestamp caps, method selection by held-out RMSE. |
| Temporal analysis | `test_temporal.py` | Interpolation, seasonal decomposition, trends, change points. |
| ML layer | `test_ml_*.py`, `test_explainability.py` | Split generators (station/year/sector/block), fold-local preprocessing, bounded search, baselines, metrics + bootstrap CIs, permutation/SHAP/PDP explanations, model artifact round-trips. |
| Reporting and reproducibility | `test_reporting.py`, `test_report_pdf.py`, `test_api_exports.py`, `test_reproduce_run.py` | Deterministic bundles, tamper detection, PDF report validity + byte-determinism, bundle verify/reproduce round-trips. |
| API end-to-end | `test_api*.py` | Upload→probe→dataset→seal→analyze/model→export/report flows, idempotency, and the 404/409/422/429 error contract. |
| Worker and jobs | `test_worker*.py` | Claim/skip-locked, heartbeats, terminal-state guards, cancellation, stale recovery. |
| Persistence | `test_repositories.py`, `test_migrations.py` | Content-addressed artifacts with ownership links, migration up/down. |
| Contracts | `test_contracts.py` | Snapshot current, examples validate, compatibility negotiation. |

Frontend: `pnpm --dir frontend test` (Vitest, 52 tests) and
`pnpm --dir frontend exec playwright test --project=chromium` (full-stack E2E:
upload→analyze→animation→export, ML train→report, contact form).
