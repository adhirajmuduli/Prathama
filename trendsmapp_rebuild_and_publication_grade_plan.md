# Trendsmapp Rebuild and Publication-Grade Implementation Plan

## Document purpose

This document defines the complete replacement architecture for the current Trendsmapp prototype. It is an implementation plan, not a conceptual wishlist. Every listed production file must be implemented as a functional component with tests, typed contracts, documented failure modes, and integration coverage. Empty modules, placeholder functions, mocked production paths, silent fallbacks, and duplicate scientific implementations are prohibited.

The implementation target is deliberately constrained to a one-to-two-week focused build. The first release will therefore prioritize a complete, reproducible vertical slice:

- upload and parse environmental monitoring data;
- normalize the data into a canonical observation model;
- preserve raw values, transformations, provenance, and hashes;
- perform explicit QC without silently deleting observations;
- generate validated spatial surfaces and temporal animations;
- train leakage-resistant tabular regression models;
- generate uncertainty and explainability outputs;
- expose a versioned FastAPI surface;
- render the workflow through a typed Next.js frontend;
- deploy the public frontend through Netlify;
- protect the contact workflow with Cloudflare Turnstile, Upstash, and Resend;
- provide automated tests, reproducibility manifests, documentation, and CI gates.

The application is not being designed as a JOSS submission. Its software rigor is intended to support a high-quality ecological or environmental machine-learning study in which Chilika Lagoon is the main scientific case study.

---

# 1. Architectural decisions

## 1.1 Public deployment topology

Netlify is the public web deployment, but it must not execute the scientific backend.

The deployment consists of:

1. `frontend/`
   - Next.js App Router application.
   - Deployed on Netlify through the supported Next.js adapter.
   - Hosts static pages, server-rendered pages, and the contact route.
   - Uses Cloudflare Turnstile, Upstash Redis rate limiting, and Resend only in the server-side contact route.
   - Calls the scientific API through a configured HTTPS backend origin.

2. `backend/`
   - FastAPI application packaged as an OCI/Docker image.
   - Deployed to a persistent container service capable of Python geospatial packages, FFmpeg, CPU-intensive model fitting, and worker processes.
   - Exposes `/api/v1`.
   - Uses PostgreSQL for metadata and job state.
   - Uses an S3-compatible object store for raw uploads, normalized datasets, model artifacts, rasters, videos, and export bundles.
   - Runs a separate worker process from the same image.

3. PostgreSQL
   - Stores dataset metadata, hashes, recipes, jobs, runs, artifact references, station registry records, parameter registry records, and compatibility metadata.
   - Does not store every normalized observation row for the first release. Normalized observations are stored as deterministic Parquet artifacts.

4. S3-compatible object storage
   - Stores immutable content-addressed artifacts.
   - Local filesystem implementation is used only in development and tests.
   - Production uses the S3 adapter.

5. Upstash Redis
   - Rate-limits the contact endpoint.
   - Provides short-lived idempotency and abuse-control keys for public job creation.
   - Does not store scientific datasets or serve as the main job queue.

6. Worker
   - Polls the PostgreSQL job table using transactional row locking.
   - Executes ingestion, spatial analysis, animation, ML, explainability, and export jobs.
   - Writes progress and terminal status to PostgreSQL.
   - Stores all outputs in object storage.

## 1.2 Why the backend is not a Netlify Function

The scientific workload includes large uploads, chunked parsing, GeoPandas/Shapely/PROJ operations, cross-validation, model fitting, SHAP calculations, raster generation, and FFmpeg video encoding. These are long-running, memory-sensitive tasks with native dependencies. They must run in a container service, not in a short-lived frontend function.

Netlify remains the canonical public deployment and domain. The frontend may use a stable API subdomain or a Netlify rewrite once the backend production URL is fixed.

## 1.3 Technology choices

### Backend

- Python 3.13 for the initial rebuild.
- FastAPI and Pydantic v2.
- SQLAlchemy 2 and Alembic.
- PostgreSQL.
- Pandas and PyArrow for tabular processing.
- OpenPyXL in read-only mode for `.xlsx`.
- GeoPandas, Shapely, PyProj, Rasterio, and SciPy.
- PyKrige for ordinary kriging.
- scikit-learn for preprocessing, baselines, Random Forest, Extra Trees, histogram gradient boosting, Gaussian-process regression, metrics, and model-selection primitives.
- XGBoost as the primary external gradient-boosting model.
- SHAP for tree-model explanations.
- Pint for units.
- Matplotlib for publication figures.
- ImageIO and FFmpeg for MP4 output.
- Structlog or standard JSON logging with one consistent configuration.
- Pytest, Hypothesis, MyPy, Ruff, and coverage.py.

### Frontend

- Next.js App Router.
- React and strict TypeScript.
- pnpm with a committed lockfile.
- Zod for browser and form boundary validation.
- TanStack Query for API state.
- React Hook Form for scientific recipe forms and contact form.
- React Leaflet and Leaflet for maps.
- Recharts or lightweight SVG components for metrics and trend plots.
- Vitest, React Testing Library, MSW for component-level boundary tests, and Playwright for real end-to-end tests.
- ESLint flat configuration in `eslint.config.mjs`.
- PostCSS and Tailwind CSS, or CSS modules where map-specific styling is clearer.

### Package and dependency policy

- Exact dependency resolution is committed through `uv.lock` in `backend/` and `pnpm-lock.yaml` in `frontend/`.
- `pyproject.toml` is the only backend package and tool configuration source.
- No manually maintained `requirements.txt` is authoritative.
- The CI image installs from the lockfiles.
- Production model implementations are imported from documented open-source libraries; Trendsmapp implements adapters, validation, provenance, and scientific workflow logic rather than reimplementing tree algorithms.

---

# 2. Scope control

## 2.1 Required for the first complete release

- Long and wide CSV/TSV ingestion.
- `.xlsx` ingestion.
- Parquet ingestion.
- Chunked upload protocol.
- Chunked parsing for delimited files.
- Canonical observation schema.
- Explicit column mapping.
- Parameter and unit normalization.
- Coordinate validation and projection.
- Duplicate and missingness handling.
- Detection-limit qualifiers.
- QC flags and reports.
- Boundary validation and masking.
- IDW, RBF, ordinary kriging, and Gaussian-process spatial methods.
- Station-holdout and spatial-block validation.
- Linear or PCHIP temporal interpolation without default extrapolation.
- Static rasters, legends, and station overlays.
- MP4 generation from observed and interpolated frames.
- Regression task configuration.
- Baseline, Elastic Net, Random Forest, Extra Trees, histogram gradient boosting, and XGBoost.
- Temporal, grouped-station, spatial-block, and combined spatiotemporal splits.
- Nested or clearly separated tuning and final evaluation.
- MAE, RMSE, R², bias, normalized RMSE, and interval coverage where available.
- Permutation importance and SHAP for supported models.
- Reproducibility manifest and export bundle.
- Contact form with Turnstile, Upstash, and Resend.
- Backend, frontend, contract, integration, and E2E tests.
- Netlify frontend deployment and containerized backend deployment.

## 2.2 Deferred after the first complete release

These must not be represented by empty files or disabled controls. They are omitted until implemented:

- user accounts and collaborative workspaces;
- public dataset catalogue;
- remote-sensing ingestion;
- distributed training;
- GPU-specific training paths;
- live WebSockets;
- general-purpose no-code pipeline editing;
- arbitrary user Python execution;
- deep-learning models;
- causal inference claims;
- automated scientific conclusions;
- mobile-native applications.

---

# 3. Non-negotiable invariants

1. Raw uploads are immutable.
2. Raw values are never overwritten by normalized values.
3. Every transformation produces a new artifact and provenance event.
4. Every stored artifact has a SHA-256 hash.
5. Every analysis run records dataset hash, boundary hash, recipe hash, software version, dependency-lock hash, random seeds, runtime environment, and output hashes.
6. Parsing, normalization, QC, interpolation, visualization, ML, and API handling remain separate layers.
7. Frontend code never performs scientific interpolation, QC, normalization, or model fitting.
8. HTTP route handlers never contain scientific calculations.
9. ORM models never act as API response models.
10. Missing values, invalid values, censored values, and excluded values remain distinguishable.
11. QC flags do not automatically delete observations.
12. Model preprocessing is fitted within the training fold.
13. Random row splitting is not the default evaluation strategy.
14. Interpolated frames and observed timestamps are visibly distinguishable.
15. Spatial calculations use projected coordinates; longitude and latitude degrees are not treated as planar distances.
16. Unknown major contract versions are rejected.
17. Compatible minor response additions are ignored safely by older clients.
18. Stored manifests are migrated through explicit pure migration functions.
19. Public `__init__.py` files contain exports and package metadata only; they do not execute database connections, register routes, read environment variables, or perform scientific work.
20. No production file is merged while containing `pass`, `NotImplementedError`, TODO-only execution branches, dummy data, or mock output.

---

# 4. Canonical contracts and compatibility

## 4.1 Versioning rules

Three versions are tracked independently:

- Application version: semantic version of Trendsmapp.
- API version: path-based major version, initially `/api/v1`.
- Artifact schema version: semantic version embedded in every stored manifest and result document.

Compatibility policy:

- API breaking changes require `/api/v2`.
- Additive response fields are allowed within `/api/v1`.
- Required request fields cannot be added without either defaults or a new API major version.
- Every request includes or implies a supported recipe schema version.
- Every result includes `schema_version`, `application_version`, and `run_id`.
- Pydantic request models reject unknown fields where accepting them could alter scientific meaning.
- Response consumers ignore unknown additive fields.
- Stored schemas are migrated one version at a time by deterministic migration functions.
- Contract examples are validated in CI against the current schemas.
- OpenAPI is exported from the backend and used to generate frontend types.
- CI fails if backend OpenAPI changes without regenerated frontend contracts and an updated compatibility note.

## 4.2 Canonical observation

The normalized observation model contains:

- `observation_id`
- `dataset_id`
- `dataset_version_id`
- `source_row`
- `source_sheet`
- `station_id`
- `station_label`
- `latitude_wgs84`
- `longitude_wgs84`
- `x_projected_m`
- `y_projected_m`
- `source_crs`
- `analysis_crs`
- `sector`
- `sampled_at`
- `sampling_depth_m`
- `parameter_id`
- `parameter_label`
- `raw_value`
- `raw_unit`
- `value_qualifier`
- `canonical_value`
- `canonical_unit`
- `detection_limit`
- `method_id`
- `instrument_id`
- `qc_status`
- `qc_flags`
- `is_excluded`
- `exclusion_reason`
- `provenance_ids`

The initial implementation may leave optional metadata null when historical sources do not provide it, but it must preserve the distinction between absent metadata and inferred metadata.

## 4.3 Hashes

The following hashes are mandatory:

- raw upload SHA-256 over the exact uploaded bytes;
- individual chunk SHA-256 for resumable upload integrity;
- completed upload SHA-256;
- normalized dataset SHA-256 over deterministic Parquet bytes;
- boundary SHA-256 over canonicalized GeoJSON;
- recipe SHA-256 over canonical JSON;
- feature matrix SHA-256;
- trained model SHA-256;
- result payload SHA-256;
- video SHA-256;
- export bundle SHA-256;
- lockfile SHA-256;
- run-manifest SHA-256.

Canonical JSON uses UTF-8, sorted keys, normalized finite numeric representations, no insignificant whitespace, and explicit null values where contractually meaningful.

---

# 5. Required repository structure

## 5.1 Root

- `README.md`
  - Project purpose, local setup, architecture summary, development commands, deployment boundaries, and links to scientific documentation.
- `LICENSE`
  - Repository license.
- `SECURITY.md`
  - Supported versions, responsible disclosure, secret handling, upload threat model, and dependency response process.
- `CONTRIBUTING.md`
  - Branching, commit, test, schema-change, scientific-review, and documentation rules.
- `CHANGELOG.md`
  - User-visible and contract-visible changes.
- `CITATION.cff`
  - Software citation metadata.
- `netlify.toml`
  - Netlify build base, frontend build command, headers, cache rules, deploy contexts, and safe redirects.
- `docker-compose.yml`
  - Local PostgreSQL, object-store-compatible service, backend API, and worker.
- `Makefile`
  - Stable developer commands that delegate to backend and frontend tooling.
- `.editorconfig`
  - Shared newline, encoding, and indentation rules.
- `.gitignore`
  - Excludes secrets, local artifacts, caches, generated reports, databases, and object-store data.
- `.gitattributes`
  - Text normalization and Git LFS only for genuinely large tracked research fixtures.
- `.env.example`
  - Variable names, safe local URLs, and non-secret development defaults. No production secrets.
- `.pre-commit-config.yaml`
  - Ruff, formatting, whitespace, secret scanning, and file-integrity checks.
- `contracts/README.md`
  - Contract-generation and compatibility procedure.
- `contracts/openapi.v1.json`
  - Generated OpenAPI snapshot committed for review.
- `contracts/schema-versions.json`
  - Supported API, recipe, manifest, and result schema versions.
- `contracts/examples/`
  - Valid minimal and full request/response examples used by both test suites.
- `docs/architecture.md`
  - Component boundaries and data flow.
- `docs/data-contract.md`
  - Canonical observation and metadata semantics.
- `docs/scientific-methods.md`
  - Interpolation, validation, temporal interpolation, ML, uncertainty, and explanation methods.
- `docs/reproducibility.md`
  - Hashing, seeds, manifests, environment capture, and reproduction procedure.
- `docs/deployment.md`
  - Netlify frontend and container backend deployment.
- `docs/publication-workflow.md`
  - How to freeze a dataset version, run a study, export tables and figures, and reproduce the manuscript outputs.
- `scripts/check_no_stubs.py`
  - Fails when production paths contain prohibited placeholder constructs.
- `scripts/hash_lockfiles.py`
  - Emits deterministic hashes for dependency locks.
- `scripts/verify_contract_examples.py`
  - Validates committed examples against backend schemas.

## 5.2 Backend root

- `backend/pyproject.toml`
  - Build metadata, Python requirement, dependency groups, console scripts, Ruff, MyPy, Pytest, and coverage configuration.
- `backend/uv.lock`
  - Exact resolved dependency graph.
- `backend/README.md`
  - Backend-specific setup, commands, API and worker operation.
- `backend/Dockerfile`
  - Multi-stage image with Python, PROJ/GDAL-compatible runtime libraries, FFmpeg, non-root user, health check, and separate API or worker command.
- `backend/alembic.ini`
  - Alembic configuration.
- `backend/migrations/env.py`
  - Migration environment bound to persistence metadata.
- `backend/migrations/script.py.mako`
  - Migration template.
- `backend/migrations/versions/0001_initial.py`
  - Complete initial schema for metadata, jobs, registries, runs, and artifacts.
- `backend/scripts/export_openapi.py`
  - Imports the application factory without starting services and writes deterministic OpenAPI JSON.
- `backend/scripts/seed_registries.py`
  - Loads versioned parameter and QC registries into PostgreSQL idempotently.
- `backend/scripts/reproduce_run.py`
  - Re-executes an exported run manifest through public workflow services.
- `backend/src/trendsmapp/py.typed`
  - PEP 561 marker declaring distributed inline type information.
- `backend/tests/`
  - Unit, property, integration, scientific regression, API, worker, and reproduction tests.
- `backend/testdata/`
  - Small licensed or synthetic deterministic fixtures, including long CSV, wide CSV, malformed CSV, XLSX, Parquet, boundary GeoJSON, and expected result manifests.

## 5.3 Backend package

### Package and shared infrastructure

- `backend/src/trendsmapp/__init__.py`
  - Exports `__version__`, supported schema versions, and stable public package names only.
- `backend/src/trendsmapp/version.py`
  - Application version and build metadata access.
- `backend/src/trendsmapp/settings.py`
  - Pydantic settings loaded once at process startup; validates all required production configuration.
- `backend/src/trendsmapp/constants.py`
  - Non-secret size limits, supported extensions, chunk size bounds, and numerical tolerances.
- `backend/src/trendsmapp/logging_config.py`
  - Structured logging, request and job correlation IDs, redaction, and JSON output.
- `backend/src/trendsmapp/errors.py`
  - Typed domain, parsing, compatibility, storage, scientific, and job exceptions.
- `backend/src/trendsmapp/hashing.py`
  - Streaming SHA-256, canonical JSON hashing, file verification, and hash comparison.
- `backend/src/trendsmapp/serialization.py`
  - Canonical JSON and deterministic manifest serialization.
- `backend/src/trendsmapp/clock.py`
  - UTC clock abstraction used for deterministic tests without embedding time logic throughout the code.

### Contracts

- `backend/src/trendsmapp/contracts/__init__.py`
  - Curated exports of contract models.
- `backend/src/trendsmapp/contracts/versions.py`
  - Supported schema versions and compatibility predicates.
- `backend/src/trendsmapp/contracts/common.py`
  - IDs, hashes, artifact references, pagination, warnings, and provenance references.
- `backend/src/trendsmapp/contracts/datasets.py`
  - Upload, chunk, parsing, column mapping, dataset manifest, and parse-report contracts.
- `backend/src/trendsmapp/contracts/recipes.py`
  - Full analysis recipe and nested QC, normalization, spatial, temporal, visualization, and export configuration.
- `backend/src/trendsmapp/contracts/jobs.py`
  - Job creation, status, progress, cancellation, and failure payloads.
- `backend/src/trendsmapp/contracts/spatial.py`
  - Grid, method, variogram, validation, raster, and uncertainty result contracts.
- `backend/src/trendsmapp/contracts/temporal.py`
  - Temporal alignment, interpolation, frame, seasonal grouping, and trend contracts.
- `backend/src/trendsmapp/contracts/ml.py`
  - Prediction task, feature specification, split strategy, model selection, search, metrics, and explanation contracts.
- `backend/src/trendsmapp/contracts/results.py`
  - Analysis summary, model result, artifact index, and export bundle contracts.
- `backend/src/trendsmapp/contracts/api_errors.py`
  - Stable machine-readable API error envelope.
- `backend/src/trendsmapp/contracts/compatibility.py`
  - Request-version negotiation and response compatibility metadata.
- `backend/src/trendsmapp/contracts/migrations.py`
  - Pure, sequential artifact-schema migrations with no I/O.

### Domain

- `backend/src/trendsmapp/domain/__init__.py`
  - Stable domain exports only.
- `backend/src/trendsmapp/domain/enums.py`
  - Controlled scientific and workflow enumerations.
- `backend/src/trendsmapp/domain/identifiers.py`
  - Typed ID constructors and validation.
- `backend/src/trendsmapp/domain/models.py`
  - Canonical domain models for observation, station, parameter, method, boundary, dataset version, recipe, run, and artifact.
- `backend/src/trendsmapp/domain/provenance.py`
  - Provenance events, parent-child artifact relationships, and transformation records.
- `backend/src/trendsmapp/domain/units.py`
  - Unit registry, canonical units, dimensional compatibility, and conversion outcomes.
- `backend/src/trendsmapp/domain/policies.py`
  - Explicit duplicate, exclusion, censoring, and extrapolation policies.

`domain/models.py` is not an ORM file. It represents scientific meaning independent of HTTP, SQLAlchemy, storage, or UI.

### Ingestion

- `backend/src/trendsmapp/ingestion/__init__.py`
  - Public ingestion service exports.
- `backend/src/trendsmapp/ingestion/file_types.py`
  - MIME, extension, magic-byte, and container checks.
- `backend/src/trendsmapp/ingestion/sniffing.py`
  - Encoding, delimiter, header, decimal, date-label, and layout detection with confidence and warnings.
- `backend/src/trendsmapp/ingestion/chunking.py`
  - Network chunk validation and streaming record-batch utilities.
- `backend/src/trendsmapp/ingestion/csv_reader.py`
  - PyArrow-based chunked CSV/TSV reader with explicit parse options.
- `backend/src/trendsmapp/ingestion/excel_reader.py`
  - Read-only `.xlsx` reader with sheet, cell, formula, and decompression limits.
- `backend/src/trendsmapp/ingestion/parquet_reader.py`
  - Row-group-aware Parquet reader and schema inspection.
- `backend/src/trendsmapp/ingestion/column_mapping.py`
  - Resolves user mapping and recognized aliases into canonical field roles.
- `backend/src/trendsmapp/ingestion/wide_to_long.py`
  - Deterministic conversion of station-by-time wide sheets to canonical long rows.
- `backend/src/trendsmapp/ingestion/parser.py`
  - Orchestrates format detection, selected reader, mapping, chunk conversion, and parse reporting.
- `backend/src/trendsmapp/ingestion/security.py`
  - File-size, workbook, archive, path, formula, and resource-exhaustion defenses.

### Normalization

- `backend/src/trendsmapp/normalization/__init__.py`
  - Public normalization pipeline exports.
- `backend/src/trendsmapp/normalization/timestamps.py`
  - Explicit timezone, date-order, precision, and ambiguous-date handling.
- `backend/src/trendsmapp/normalization/coordinates.py`
  - Coordinate coercion, WGS84 validation, CRS conversion, and projected coordinates.
- `backend/src/trendsmapp/normalization/parameters.py`
  - Parameter alias resolution and registry matching.
- `backend/src/trendsmapp/normalization/values.py`
  - Numeric parsing, decimal conventions, qualifiers, infinities, and detection-limit representation.
- `backend/src/trendsmapp/normalization/units.py`
  - Raw-unit parsing and conversion to parameter-specific canonical units.
- `backend/src/trendsmapp/normalization/duplicates.py`
  - Duplicate classification and configured resolution while preserving source lineage.
- `backend/src/trendsmapp/normalization/canonicalize.py`
  - Produces ordered canonical Arrow batches and deterministic Parquet.
- `backend/src/trendsmapp/normalization/pipeline.py`
  - Executes normalization stages and emits provenance plus a normalization report.

### Quality control

- `backend/src/trendsmapp/qc/__init__.py`
  - Public QC exports.
- `backend/src/trendsmapp/qc/models.py`
  - QC rule result, flag, severity, exclusion decision, and summary models.
- `backend/src/trendsmapp/qc/coordinates.py`
  - Lagoon-boundary, valid-range, duplicate-location, and station-drift checks.
- `backend/src/trendsmapp/qc/completeness.py`
  - Missingness by row, field, station, parameter, season, and year.
- `backend/src/trendsmapp/qc/duplicates.py`
  - Exact and semantic duplicate flags.
- `backend/src/trendsmapp/qc/ranges.py`
  - Registry-driven physical and method-validity ranges.
- `backend/src/trendsmapp/qc/detection_limits.py`
  - Censoring and detection-limit consistency.
- `backend/src/trendsmapp/qc/outliers.py`
  - Robust within-parameter and context-aware statistical flags; no automatic deletion.
- `backend/src/trendsmapp/qc/temporal.py`
  - Abrupt jumps, impossible timestamps, repeated visits, and sampling-gap flags.
- `backend/src/trendsmapp/qc/pipeline.py`
  - Deterministic rule execution, aggregate status, optional explicit exclusions, and QC artifact generation.

### Geospatial foundation

- `backend/src/trendsmapp/geospatial/__init__.py`
  - Stable geospatial utility exports.
- `backend/src/trendsmapp/geospatial/crs.py`
  - CRS validation, cached PyProj transformers, axis-order safety, and analysis-CRS choice.
- `backend/src/trendsmapp/geospatial/boundary.py`
  - GeoJSON parsing, geometry validation, canonicalization, optional `make_valid` provenance, and hash generation.
- `backend/src/trendsmapp/geospatial/grid.py`
  - Grid resolution, extent, cell centers, maximum cell limits, and mask alignment.
- `backend/src/trendsmapp/geospatial/masking.py`
  - Vectorized lagoon mask generation and raster nodata application.
- `backend/src/trendsmapp/geospatial/distance.py`
  - Projected Euclidean distances and optional geodesic diagnostics.
- `backend/src/trendsmapp/geospatial/sectors.py`
  - Sector polygon loading, point assignment, and ambiguity reporting.

### Spatial analysis

- `backend/src/trendsmapp/spatial/__init__.py`
  - Public spatial method and result exports.
- `backend/src/trendsmapp/spatial/base.py`
  - Common interpolator protocol, fitted result model, and method capability declarations.
- `backend/src/trendsmapp/spatial/idw.py`
  - Deterministic IDW with distance floor, configurable power, neighbor limit, and support-distance output.
- `backend/src/trendsmapp/spatial/rbf.py`
  - SciPy `RBFInterpolator` adapter with explicit kernel, smoothing, and neighbor settings.
- `backend/src/trendsmapp/spatial/kriging.py`
  - PyKrige ordinary-kriging adapter, variogram configuration, prediction, and kriging variance.
- `backend/src/trendsmapp/spatial/gaussian_process.py`
  - scikit-learn Gaussian-process adapter returning predictive mean and standard deviation.
- `backend/src/trendsmapp/spatial/registry.py`
  - Maps recipe method identifiers to validated functional implementations.
- `backend/src/trendsmapp/spatial/validation.py`
  - Leave-one-station-out, grouped holdout, and spatial-block validation.
- `backend/src/trendsmapp/spatial/uncertainty.py`
  - Normalizes method-specific uncertainty and sampling-support diagnostics into a common payload.
- `backend/src/trendsmapp/spatial/raster.py`
  - Writes GeoTIFF, masked PNG, extent metadata, and checksums.
- `backend/src/trendsmapp/spatial/pipeline.py`
  - Runs selected methods per parameter and timestamp, validates them, selects only by declared rule, and stores outputs.

### Temporal analysis

- `backend/src/trendsmapp/temporal/__init__.py`
  - Public temporal exports.
- `backend/src/trendsmapp/temporal/alignment.py`
  - Groups observations by explicit resolution and identifies observed versus missing periods.
- `backend/src/trendsmapp/temporal/interpolation.py`
  - Linear and PCHIP interpolation with maximum-gap constraints and no default extrapolation.
- `backend/src/trendsmapp/temporal/seasonal.py`
  - Configurable month, monsoon, and user-defined seasonal labels.
- `backend/src/trendsmapp/temporal/trends.py`
  - Descriptive trend estimates, robust slopes, confidence intervals, and autocorrelation-aware reporting.
- `backend/src/trendsmapp/temporal/change_points.py`
  - Optional configured change-point analysis that reports method assumptions and minimum segment limits.
- `backend/src/trendsmapp/temporal/pipeline.py`
  - Produces time-aligned station series, interpolated frame inputs, seasonal summaries, and trend artifacts.

### Feature engineering

- `backend/src/trendsmapp/features/__init__.py`
  - Public feature-building exports.
- `backend/src/trendsmapp/features/calendar.py`
  - Cyclical month/day features and explicit seasonal categories.
- `backend/src/trendsmapp/features/lags.py`
  - Leakage-safe lag and rolling features computed only from available prior observations.
- `backend/src/trendsmapp/features/spatial.py`
  - Coordinates, sector, distance-to-boundary, station identity policy, and spatial context.
- `backend/src/trendsmapp/features/missingness.py`
  - Missingness indicators and availability metadata.
- `backend/src/trendsmapp/features/builder.py`
  - Builds the feature table from a declared task and records feature lineage.

### Machine learning

- `backend/src/trendsmapp/ml/__init__.py`
  - Stable ML public API.
- `backend/src/trendsmapp/ml/models.py`
  - Functional estimator registry and adapters for each approved model family.
- `backend/src/trendsmapp/ml/baselines.py`
  - Mean, median, station climatology, seasonal climatology, and persistence baselines.
- `backend/src/trendsmapp/ml/preprocessing.py`
  - scikit-learn `ColumnTransformer` and `Pipeline` construction with fold-local imputation, encoding, scaling, and transformation.
- `backend/src/trendsmapp/ml/splits.py`
  - Station-group, spatial-block, leave-year-out, rolling-origin, sector, and combined split generators.
- `backend/src/trendsmapp/ml/search.py`
  - Reproducible bounded hyperparameter search using the configured inner split.
- `backend/src/trendsmapp/ml/training.py`
  - Outer evaluation, inner tuning, fold artifact collection, final refit, seed control, and failure reporting.
- `backend/src/trendsmapp/ml/metrics.py`
  - Regression metrics, bootstrap confidence intervals, fold aggregation, and subgroup metrics.
- `backend/src/trendsmapp/ml/uncertainty.py`
  - Bootstrap ensemble or quantile-based intervals and empirical coverage.
- `backend/src/trendsmapp/ml/artifacts.py`
  - Safe model serialization, feature schema, environment metadata, hashes, and load-time compatibility checks.
- `backend/src/trendsmapp/ml/pipeline.py`
  - End-to-end task validation, feature generation, training, evaluation, explanation dispatch, and result storage.

`ml/models.py` imports documented estimators. It does not copy Random Forest, XGBoost, or gradient-boosting source code.

Initial approved model identifiers:

- `mean_baseline`
- `station_climatology`
- `seasonal_climatology`
- `elastic_net`
- `random_forest`
- `extra_trees`
- `hist_gradient_boosting`
- `xgboost`

CatBoost may be added later through the same registry if categorical-feature handling is central to a specific experiment. It is not required in the first vertical slice because XGBoost plus scikit-learn ensembles already provide a sufficient comparison set.

### Explainability

- `backend/src/trendsmapp/explainability/__init__.py`
  - Stable explanation exports.
- `backend/src/trendsmapp/explainability/permutation.py`
  - Held-out permutation importance with repeated seeds.
- `backend/src/trendsmapp/explainability/shap_values.py`
  - SHAP dispatch for supported fitted tree models with bounded background and sample sizes.
- `backend/src/trendsmapp/explainability/effects.py`
  - Partial dependence or accumulated-effect payloads only when configured and valid.
- `backend/src/trendsmapp/explainability/stability.py`
  - Importance rank and direction stability across folds, years, and sectors.
- `backend/src/trendsmapp/explainability/payloads.py`
  - Renderer-neutral explanation tables and plot-ready arrays.
- `backend/src/trendsmapp/explainability/pipeline.py`
  - Executes only explanations supported by the model and task; records limitations rather than substituting another method silently.

### Visualization and animation

- `backend/src/trendsmapp/visualization/__init__.py`
  - Public visualization exports.
- `backend/src/trendsmapp/visualization/scales.py`
  - Physical, robust, global-sequence, and user-defined scale calculation.
- `backend/src/trendsmapp/visualization/palettes.py`
  - Approved perceptually suitable palettes and reversal rules.
- `backend/src/trendsmapp/visualization/heatmap.py`
  - Publication PNG and frontend overlay rendering from raster outputs.
- `backend/src/trendsmapp/visualization/legend.py`
  - Unit-aware legends and observed/interpolated labels.
- `backend/src/trendsmapp/visualization/animation.py`
  - Frame scheduling, rendering, FFmpeg invocation, metadata, cancellation checks, and MP4 validation.
- `backend/src/trendsmapp/visualization/figures.py`
  - Cross-validation, residual, trend, importance, and uncertainty figures.
- `backend/src/trendsmapp/visualization/pipeline.py`
  - Converts scientific result artifacts into web and publication outputs without recalculating the science.

### Reporting and reproducibility

- `backend/src/trendsmapp/reporting/__init__.py`
  - Public report exports.
- `backend/src/trendsmapp/reporting/tables.py`
  - CSV and Parquet tables for QC, metrics, folds, predictions, importance, and summaries.
- `backend/src/trendsmapp/reporting/manifest.py`
  - Builds the complete run manifest.
- `backend/src/trendsmapp/reporting/methods.py`
  - Generates a factual methods record from the executed recipe and software versions.
- `backend/src/trendsmapp/reporting/bundle.py`
  - Creates the immutable ZIP export with manifest, data dictionary, recipes, results, figures, checksums, and reproduction command.
- `backend/src/trendsmapp/reporting/verify.py`
  - Verifies every checksum and contract in an exported bundle.

### Storage

- `backend/src/trendsmapp/storage/__init__.py`
  - Storage factory exports.
- `backend/src/trendsmapp/storage/base.py`
  - Object-store protocol and typed results.
- `backend/src/trendsmapp/storage/paths.py`
  - Valid content-addressed key construction; rejects traversal and arbitrary user paths.
- `backend/src/trendsmapp/storage/local.py`
  - Atomic local filesystem implementation for development and tests.
- `backend/src/trendsmapp/storage/s3.py`
  - S3-compatible multipart upload, streaming download, metadata, and checksum implementation.
- `backend/src/trendsmapp/storage/factory.py`
  - Selects the configured adapter and validates capability at startup.

### Persistence

- `backend/src/trendsmapp/persistence/__init__.py`
  - Database factory and repository exports.
- `backend/src/trendsmapp/persistence/database.py`
  - Async engine, session factory, health check, transaction boundary, and shutdown.
- `backend/src/trendsmapp/persistence/models.py`
  - SQLAlchemy ORM tables only.
- `backend/src/trendsmapp/persistence/repositories/datasets.py`
  - Dataset and version persistence.
- `backend/src/trendsmapp/persistence/repositories/uploads.py`
  - Chunk and upload-session persistence.
- `backend/src/trendsmapp/persistence/repositories/jobs.py`
  - Job creation, claim, progress, cancellation, heartbeat, and terminal state.
- `backend/src/trendsmapp/persistence/repositories/runs.py`
  - Recipe and run metadata.
- `backend/src/trendsmapp/persistence/repositories/artifacts.py`
  - Artifact references and hash uniqueness.
- `backend/src/trendsmapp/persistence/repositories/registries.py`
  - Parameter, method, and station registry access.

`persistence/models.py` is not imported by frontend-facing contracts. Repository methods translate between ORM rows and domain models.

### Application services

- `backend/src/trendsmapp/services/__init__.py`
  - Application-service exports.
- `backend/src/trendsmapp/services/uploads.py`
  - Creates upload sessions, validates parts, completes uploads, and schedules parsing.
- `backend/src/trendsmapp/services/datasets.py`
  - Dataset metadata, mappings, versions, and parse/QC summaries.
- `backend/src/trendsmapp/services/analyses.py`
  - Validates recipes, enforces dataset compatibility, creates analysis jobs, and returns result indices.
- `backend/src/trendsmapp/services/models.py`
  - Creates ML jobs and exposes model artifacts and metrics.
- `backend/src/trendsmapp/services/artifacts.py`
  - Authorizes artifact lookup, streams downloads, and verifies hashes.
- `backend/src/trendsmapp/services/capabilities.py`
  - Reports supported formats, methods, model families, versions, and configured limits.

### Workflows

- `backend/src/trendsmapp/workflows/__init__.py`
  - Public workflow registry.
- `backend/src/trendsmapp/workflows/context.py`
  - Run context containing services, repositories, storage, cancellation token, logger, seeds, and provenance collector.
- `backend/src/trendsmapp/workflows/ingest.py`
  - Raw upload to parsed, normalized, QC-annotated Parquet dataset version.
- `backend/src/trendsmapp/workflows/analyze.py`
  - Dataset version to temporal summaries, spatial validation, rasters, uncertainty, and figures.
- `backend/src/trendsmapp/workflows/train.py`
  - Dataset version and ML task to evaluated model and explanations.
- `backend/src/trendsmapp/workflows/animate.py`
  - Existing spatial outputs and temporal frames to an MP4 artifact.
- `backend/src/trendsmapp/workflows/export.py`
  - Run artifacts to a verified reproducibility bundle.
- `backend/src/trendsmapp/workflows/registry.py`
  - Maps job type to the exact workflow handler.

### API

- `backend/src/trendsmapp/api/__init__.py`
  - Application factory export.
- `backend/src/trendsmapp/api/app.py`
  - FastAPI application factory, lifespan, routers, middleware, and OpenAPI metadata.
- `backend/src/trendsmapp/api/dependencies.py`
  - Dependency providers for settings, sessions, repositories, services, and request context.
- `backend/src/trendsmapp/api/middleware.py`
  - Request IDs, size limits, timing, trusted hosts, CORS, and safe headers.
- `backend/src/trendsmapp/api/exception_handlers.py`
  - Maps typed exceptions to stable error envelopes.
- `backend/src/trendsmapp/api/routers/health.py`
  - Liveness and readiness.
- `backend/src/trendsmapp/api/routers/capabilities.py`
  - Supported contract and method metadata.
- `backend/src/trendsmapp/api/routers/uploads.py`
  - Chunked upload lifecycle.
- `backend/src/trendsmapp/api/routers/datasets.py`
  - Mapping, parse report, dataset version, and QC endpoints.
- `backend/src/trendsmapp/api/routers/analyses.py`
  - Spatial, temporal, visualization, and animation job creation.
- `backend/src/trendsmapp/api/routers/models.py`
  - ML task validation, training job creation, metrics, and explanations.
- `backend/src/trendsmapp/api/routers/jobs.py`
  - Job status, progress, logs summary, and cancellation.
- `backend/src/trendsmapp/api/routers/artifacts.py`
  - Artifact metadata and controlled download.
- `backend/src/trendsmapp/api/routers/exports.py`
  - Reproducibility bundle creation and verification.

### Worker

- `backend/src/trendsmapp/worker/__init__.py`
  - Worker entry export.
- `backend/src/trendsmapp/worker/main.py`
  - Process lifecycle, startup validation, signal handling, and polling loop.
- `backend/src/trendsmapp/worker/queue.py`
  - PostgreSQL transactional job claiming with stale-job recovery.
- `backend/src/trendsmapp/worker/handlers.py`
  - Dispatches claimed jobs through the workflow registry.
- `backend/src/trendsmapp/worker/heartbeat.py`
  - Updates running-job health and detects worker loss.

### CLI

- `backend/src/trendsmapp/cli/__init__.py`
  - CLI app export.
- `backend/src/trendsmapp/cli/main.py`
  - Typer command group.
- `backend/src/trendsmapp/cli/validate.py`
  - Validates files, mappings, recipes, manifests, and bundles.
- `backend/src/trendsmapp/cli/ingest.py`
  - Runs the same ingestion workflow locally.
- `backend/src/trendsmapp/cli/analyze.py`
  - Runs the same spatial and temporal workflow locally.
- `backend/src/trendsmapp/cli/train.py`
  - Runs the same ML workflow locally.
- `backend/src/trendsmapp/cli/reproduce.py`
  - Reproduces a run from an export bundle and compares checksums or declared numeric tolerances.

### Versioned resources

- `backend/src/trendsmapp/resources/parameters.v1.yaml`
  - Parameter IDs, aliases, canonical units, dimensions, display names, and optional physical ranges.
- `backend/src/trendsmapp/resources/qc_ranges.v1.yaml`
  - Explicit QC ranges with source and applicability metadata.
- `backend/src/trendsmapp/resources/seasons.v1.yaml`
  - Default month and monsoon group definitions.
- `backend/src/trendsmapp/resources/chilika_sectors.v1.geojson`
  - Versioned sector boundaries with source, license, CRS, and checksum metadata.
- `backend/src/trendsmapp/resources/default_boundary.geojson`
  - Default lagoon boundary only if its source and reuse rights are documented.

## 5.4 Frontend root

- `frontend/package.json`
  - Scripts, exact package ranges constrained by the lockfile, and Node/pnpm engine requirements.
- `frontend/pnpm-lock.yaml`
  - Exact frontend dependency graph.
- `frontend/next.config.ts`
  - Security, image policy, build behavior, and Netlify-compatible Next.js configuration.
- `frontend/tsconfig.json`
  - Strict TypeScript, no unchecked indexed access, exact optional properties, and path aliases.
- `frontend/eslint.config.mjs`
  - ESLint flat configuration with Next.js, React, accessibility, import-boundary, promise, and type-aware TypeScript rules.
- `frontend/postcss.config.mjs`
  - PostCSS integration.
- `frontend/vitest.config.ts`
  - Unit and component test environment and coverage.
- `frontend/playwright.config.ts`
  - Browser matrix, local web server, traces, screenshots, and retries.
- `frontend/instrumentation.ts`
  - Server-side instrumentation and error correlation without secret leakage.
- `frontend/README.md`
  - Frontend commands, environment variables, component boundaries, and deployment.
- `frontend/public/`
  - Favicons, local fonts if licensed, static logo, example template files, and no scientific output generated at runtime.

## 5.5 Frontend application

### App routes

- `frontend/src/app/layout.tsx`
  - Root metadata, fonts, providers, skip link, and application shell.
- `frontend/src/app/page.tsx`
  - Public project description and entry into the analysis workspace.
- `frontend/src/app/workspace/page.tsx`
  - New dataset upload and recent local job references.
- `frontend/src/app/workspace/[jobId]/page.tsx`
  - Job-resumable analysis workspace.
- `frontend/src/app/methods/page.tsx`
  - Human-readable scientific methods and limitations.
- `frontend/src/app/privacy/page.tsx`
  - Upload retention, contact data, cookies, and third-party processors.
- `frontend/src/app/contact/page.tsx`
  - Contact page using the contact feature.
- `frontend/src/app/api/contact/route.ts`
  - Server-only Zod validation, Turnstile Siteverify, Upstash rate limit, idempotency, Resend dispatch, and safe response.
- `frontend/src/app/error.tsx`
  - Recoverable route error boundary.
- `frontend/src/app/global-error.tsx`
  - Root fallback.
- `frontend/src/app/not-found.tsx`
  - Accessible not-found page.
- `frontend/src/app/loading.tsx`
  - Route loading state.
- `frontend/src/app/robots.ts`
  - Search policy.
- `frontend/src/app/sitemap.ts`
  - Public routes only.

### Shared application components

- `frontend/src/components/app-shell.tsx`
  - Header, main area, footer, and responsive structure.
- `frontend/src/components/site-header.tsx`
  - Primary navigation.
- `frontend/src/components/status-banner.tsx`
  - API compatibility, degraded mode, and scientific warning messages.
- `frontend/src/components/error-panel.tsx`
  - Structured API and form error display.
- `frontend/src/components/progress-panel.tsx`
  - Multi-stage job progress.
- `frontend/src/components/download-link.tsx`
  - Artifact metadata, checksum, and download action.
- `frontend/src/components/ui/`
  - Small accessible buttons, fields, dialogs, tabs, tables, and cards. Each component remains presentational.

### Providers and state

- `frontend/src/providers/app-providers.tsx`
  - Query client, error boundary, and application-level contexts.
- `frontend/src/lib/query-client.ts`
  - TanStack Query defaults, retry policy, and cache durations.
- `frontend/src/stores/workspace-store.ts`
  - Ephemeral UI selections only. Scientific results remain server-derived.
- `frontend/src/hooks/use-job-polling.ts`
  - Polls active jobs with backoff and stops on terminal status.
- `frontend/src/hooks/use-persisted-job.ts`
  - Stores only opaque job IDs and safe UI preferences locally.

### Environment, contracts, and API

- `frontend/src/lib/env/server.ts`
  - Server-only environment validation.
- `frontend/src/lib/env/client.ts`
  - Public environment validation.
- `frontend/src/lib/api/client.ts`
  - Typed fetch client, request IDs, timeout, cancellation, and response validation.
- `frontend/src/lib/api/errors.ts`
  - Converts error envelopes to typed UI errors.
- `frontend/src/lib/api/uploads.ts`
  - Chunked-upload API calls.
- `frontend/src/lib/api/datasets.ts`
  - Dataset and mapping calls.
- `frontend/src/lib/api/analyses.ts`
  - Analysis and animation calls.
- `frontend/src/lib/api/models.ts`
  - ML task and result calls.
- `frontend/src/lib/api/jobs.ts`
  - Job polling and cancellation.
- `frontend/src/lib/contracts/generated.ts`
  - Generated OpenAPI TypeScript types; never edited manually.
- `frontend/src/lib/contracts/runtime.ts`
  - Small Zod schemas for critical runtime envelopes and contact form.
- `frontend/scripts/generate-api-types.mjs`
  - Regenerates TypeScript types from `contracts/openapi.v1.json`.
- `frontend/src/lib/security.ts`
  - Safe URL, download filename, and external-link policies.
- `frontend/src/lib/hash-file.ts`
  - Browser SHA-256 for completed file verification without loading the whole file at once.
- `frontend/src/lib/format.ts`
  - Units, dates, metrics, byte sizes, and hashes.
- `frontend/src/lib/accessibility.ts`
  - Shared announcements and focus-management helpers.

### Upload and schema mapping

- `frontend/src/features/upload/upload-panel.tsx`
  - File and boundary selection, limits, and workflow entry.
- `frontend/src/features/upload/chunked-uploader.ts`
  - Five-MiB chunk creation, bounded concurrency, per-part hashing, retry, resume, and completion verification.
- `frontend/src/features/upload/upload-progress.tsx`
  - Byte and part progress.
- `frontend/src/features/upload/column-mapping-form.tsx`
  - Explicit mapping of coordinates, station, timestamp, parameter, value, unit, qualifier, and metadata.
- `frontend/src/features/upload/layout-preview.tsx`
  - Shows detected long or wide layout and parse confidence.
- `frontend/src/features/upload/upload.schemas.ts`
  - Frontend-only form schemas aligned to the API contract.

### Dataset and QC

- `frontend/src/features/dataset/dataset-summary.tsx`
  - Dataset version, hashes, row counts, periods, stations, and parameters.
- `frontend/src/features/dataset/parse-report.tsx`
  - Parsing errors, warnings, rejected rows, and mapping decisions.
- `frontend/src/features/dataset/qc-summary.tsx`
  - QC counts by severity and rule.
- `frontend/src/features/dataset/qc-table.tsx`
  - Paginated QC findings without downloading the full dataset.
- `frontend/src/features/dataset/provenance-panel.tsx`
  - Raw-to-normalized artifact lineage.

### Analysis recipe

- `frontend/src/features/analysis/recipe-form.tsx`
  - Builds the versioned analysis recipe.
- `frontend/src/features/analysis/qc-policy-fields.tsx`
  - Explicit rule and exclusion controls.
- `frontend/src/features/analysis/spatial-fields.tsx`
  - Method, grid, variogram, neighbor, and validation settings.
- `frontend/src/features/analysis/temporal-fields.tsx`
  - Resolution, interpolation, gap, season, and frame settings.
- `frontend/src/features/analysis/visualization-fields.tsx`
  - Scale, palette, opacity, overlays, and export settings.
- `frontend/src/features/analysis/analysis-run-panel.tsx`
  - Submits a recipe and shows the immutable recipe hash.
- `frontend/src/features/analysis/result-tabs.tsx`
  - Coordinates map, validation, trends, uncertainty, animation, and exports.

### Map and time display

- `frontend/src/features/map/lagoon-map.tsx`
  - Dynamically loaded Leaflet map and layer orchestration.
- `frontend/src/features/map/raster-overlay.tsx`
  - Displays backend-produced georeferenced PNG layers.
- `frontend/src/features/map/station-layer.tsx`
  - Sanitized station markers and QC state.
- `frontend/src/features/map/boundary-layer.tsx`
  - Boundary and sector geometry.
- `frontend/src/features/map/map-legend.tsx`
  - Units, range, method, observed/interpolated state, and uncertainty legend.
- `frontend/src/features/map/time-controls.tsx`
  - Timestamp selection, playback, and observed-frame indicators.
- `frontend/src/features/map/layer-controls.tsx`
  - Heatmap, stations, uncertainty, support distance, sectors, and boundary toggles.
- `frontend/src/features/map/map-export.tsx`
  - Requests publication render from the backend; does not screenshot the browser map as the authoritative figure.

### Animation

- `frontend/src/features/animation/animation-form.tsx`
  - FPS, frame interval, duration, selected parameter, and visual configuration.
- `frontend/src/features/animation/animation-result.tsx`
  - Video metadata, observed/interpolated disclosure, playback, and verified download.

### ML and explainability

- `frontend/src/features/ml/task-form.tsx`
  - Target, features, prediction setting, holdout strategy, models, search budget, and seed.
- `frontend/src/features/ml/model-comparison.tsx`
  - Baselines and models with fold-aware metrics and intervals.
- `frontend/src/features/ml/fold-results.tsx`
  - Per-fold results and held-out groups or periods.
- `frontend/src/features/ml/residual-plots.tsx`
  - Backend-generated or renderer-neutral residual data.
- `frontend/src/features/ml/importance-panel.tsx`
  - Permutation importance and stability.
- `frontend/src/features/ml/shap-panel.tsx`
  - Global and local SHAP summaries with clear non-causality note.
- `frontend/src/features/ml/uncertainty-panel.tsx`
  - Prediction interval coverage and width.

### Export

- `frontend/src/features/export/export-panel.tsx`
  - Selects artifacts and creates a reproducibility bundle.
- `frontend/src/features/export/manifest-viewer.tsx`
  - Displays versions, hashes, seeds, methods, and limitations.
- `frontend/src/features/export/checksum-list.tsx`
  - Exposes checksums for downloaded artifacts.

### Contact

- `frontend/src/features/contact/contact-form.tsx`
  - Name, email, subject, message, consent, Turnstile token, and submission state.
- `frontend/src/features/contact/turnstile-widget.tsx`
  - Explicit widget rendering, reset, expiry, and accessible failure state.
- `frontend/src/features/contact/contact.schemas.ts`
  - Zod form and normalized server input schemas.
- `frontend/src/features/contact/email-template.tsx`
  - React email body with escaped user content and structured metadata.

### Frontend tests

- `frontend/src/**/*.test.ts`
  - Pure utility and schema tests.
- `frontend/src/**/*.test.tsx`
  - Component behavior and accessibility.
- `frontend/tests/contract/`
  - Validates runtime handling of committed API examples.
- `frontend/e2e/upload-analysis.spec.ts`
  - Upload, map, QC, analysis, and export.
- `frontend/e2e/ml.spec.ts`
  - Task configuration, training, metrics, and explainability.
- `frontend/e2e/animation.spec.ts`
  - Animation job and MP4 download.
- `frontend/e2e/contact.spec.ts`
  - Turnstile test keys, rate limit behavior, and Resend test-mode integration.
- `frontend/e2e/accessibility.spec.ts`
  - Keyboard, landmark, focus, and automated accessibility checks.

---

# 6. API surface

## 6.1 System

- `GET /api/v1/health/live`
- `GET /api/v1/health/ready`
- `GET /api/v1/capabilities`
- `GET /api/v1/contracts/versions`

## 6.2 Uploads

- `POST /api/v1/uploads`
  - Creates an upload session and returns upload ID, accepted chunk size, and expiry.
- `PUT /api/v1/uploads/{upload_id}/parts/{part_number}`
  - Accepts one chunk with byte range and SHA-256.
- `GET /api/v1/uploads/{upload_id}`
  - Returns uploaded parts and resume status.
- `POST /api/v1/uploads/{upload_id}/complete`
  - Verifies part order, byte size, and full SHA-256, then creates an ingestion job.
- `DELETE /api/v1/uploads/{upload_id}`
  - Cancels and removes incomplete parts.

## 6.3 Datasets

- `GET /api/v1/datasets/{dataset_id}`
- `GET /api/v1/datasets/{dataset_id}/versions`
- `GET /api/v1/dataset-versions/{version_id}`
- `GET /api/v1/dataset-versions/{version_id}/parse-report`
- `POST /api/v1/dataset-versions/{version_id}/mapping`
- `GET /api/v1/dataset-versions/{version_id}/qc`
- `GET /api/v1/dataset-versions/{version_id}/preview`
- `GET /api/v1/dataset-versions/{version_id}/provenance`

## 6.4 Analyses

- `POST /api/v1/analyses`
- `GET /api/v1/analyses/{run_id}`
- `GET /api/v1/analyses/{run_id}/spatial-results`
- `GET /api/v1/analyses/{run_id}/temporal-results`
- `GET /api/v1/analyses/{run_id}/artifacts`
- `POST /api/v1/analyses/{run_id}/animations`

## 6.5 Models

- `POST /api/v1/model-runs`
- `GET /api/v1/model-runs/{run_id}`
- `GET /api/v1/model-runs/{run_id}/metrics`
- `GET /api/v1/model-runs/{run_id}/folds`
- `GET /api/v1/model-runs/{run_id}/predictions`
- `GET /api/v1/model-runs/{run_id}/explanations`
- `GET /api/v1/model-runs/{run_id}/artifacts`

## 6.6 Jobs

- `GET /api/v1/jobs/{job_id}`
- `POST /api/v1/jobs/{job_id}/cancel`

## 6.7 Artifacts and exports

- `GET /api/v1/artifacts/{artifact_id}`
- `GET /api/v1/artifacts/{artifact_id}/download`
- `POST /api/v1/exports`
- `GET /api/v1/exports/{export_id}`
- `GET /api/v1/exports/{export_id}/download`

All job-creating endpoints support an idempotency key. Repeating the same key with the same request hash returns the original job; repeating it with different content returns a conflict.

---

# 7. Scientific workflow

## 7.1 Ingestion workflow

1. Browser computes the file SHA-256 incrementally.
2. Browser opens an upload session.
3. Browser uploads bounded chunks with individual hashes.
4. Backend streams each part to storage and records it transactionally.
5. Completion verifies all parts and the full upload hash.
6. Worker detects file type from content and extension.
7. Parser inspects layout, encoding, headers, sheets, and sample rows.
8. User confirms or corrects field mapping.
9. Worker reads data in chunks or row groups.
10. Wide data are converted to long form.
11. Timestamps, coordinates, parameter names, units, qualifiers, and numeric values are normalized.
12. QC rules add flags.
13. Explicit exclusion policy is applied without deleting source rows.
14. Canonical rows are sorted deterministically.
15. Canonical Parquet, parse report, normalization report, QC report, and provenance are stored.
16. Dataset version is sealed with hashes.

## 7.2 Parsing and normalization rules

- `.xls` is not accepted in the first release because it requires a legacy binary parser. Users must convert it to `.xlsx`, CSV, or Parquet.
- Formula cells are rejected as data unless their cached values are explicitly accepted and recorded.
- Timestamps are parsed under a declared date-order policy. Ambiguous values become errors or warnings, not guesses.
- Latitude and longitude remain WGS84 fields; projected coordinates are derived and recorded separately.
- Parameter aliases are resolved through a versioned registry.
- Unit conversion is dimension-checked.
- Detection-limit strings such as `<0.01` become numeric limit plus qualifier; they are not silently converted to zero.
- Non-finite values are rejected.
- Duplicate handling is recipe-controlled.
- Transformations used for ML are not written back as canonical measurements.
- Normalization never uses future or test-fold information.

## 7.3 Spatial workflow

For each parameter and observed timestamp:

1. Select observations permitted by the QC and exclusion policy.
2. Project to the analysis CRS.
3. Build a masked grid inside the lagoon boundary.
4. Fit selected methods.
5. Run station or spatial-block validation.
6. Record MAE, RMSE, bias, and valid prediction count.
7. Generate mean surface.
8. Generate method-specific uncertainty or support surface.
9. Write GeoTIFF and frontend PNG.
10. Generate legend and metadata.
11. Keep method outputs separate. Do not overwrite one method with the selected result.
12. If an automatic selection rule is used, record the rule and validation evidence.

IDW remains a transparent baseline. RBF provides a smooth deterministic alternative. Kriging provides variogram-based prediction and variance. Gaussian-process regression provides a probabilistic alternative for datasets small enough for its computational cost.

KDE is not included as a measurement interpolator. It may later be added as a sampling-density or event-density visualization under a separate method class and different units.

## 7.4 Temporal and animation workflow

1. Identify observed timestamps.
2. Align station or raster series to the requested time resolution.
3. Interpolate only across gaps within the configured maximum duration.
4. Use linear interpolation by default; PCHIP is available for shape-preserving smoothness.
5. Do not extrapolate outside observed periods unless explicitly enabled and disclosed.
6. Mark every frame as observed, interpolated, or unavailable.
7. Use one scale across a comparable animation unless a different declared policy is selected.
8. Render from stored scientific rasters, not by rerunning interpolation inside the video loop.
9. Add timestamp, parameter, unit, method, and frame-status metadata.
10. Encode MP4 through FFmpeg and verify duration, dimensions, frame count, and checksum.

## 7.5 ML workflow

A model run must declare:

- target parameter;
- prediction unit;
- prediction setting;
- eligible date range;
- eligible stations or sectors;
- feature list;
- lag policy;
- missing-data policy;
- QC and exclusion policy;
- outer evaluation strategy;
- inner tuning strategy;
- candidate models;
- search budget;
- primary metric;
- random seed;
- uncertainty method;
- explanation methods.

Initial prediction settings:

1. Known-station temporal prediction.
2. Unseen-station spatial generalization.
3. Future-period forecasting.
4. Missing-observation reconstruction.

Each setting has an allowed split family. The API rejects scientifically incompatible combinations, such as random row splitting for an unseen-station claim.

Training sequence:

1. Freeze dataset version and task recipe.
2. Build features with lineage.
3. Hash feature table.
4. Generate outer splits.
5. For each outer fold, run bounded inner search.
6. Fit all preprocessing only on the inner training data.
7. Evaluate on untouched outer test data.
8. Store fold model, predictions, metrics, held-out groups, and warnings.
9. Aggregate metrics with confidence intervals.
10. Compare every ML model against relevant baselines.
11. Fit the selected final model only after evaluation is complete.
12. Generate uncertainty and explanations.
13. Store model package, feature schema, recipe, metrics, hashes, and compatibility metadata.

## 7.6 Publication outputs

Every complete study run can export:

- dataset and variable summary;
- station and sampling coverage;
- missingness and QC tables;
- spatial validation table;
- model-comparison table;
- per-fold metrics;
- subgroup metrics by season, sector, year, and station support;
- observed versus predicted table;
- uncertainty coverage table;
- feature-importance stability table;
- static maps;
- uncertainty maps;
- trend figures;
- residual figures;
- SHAP figures;
- animation;
- methods record;
- limitations record;
- complete run manifest;
- checksums;
- machine-readable recipe;
- reproduction command.

---

# 8. Security design

## 8.1 Upload security

- Strict size limits at browser, reverse proxy, API middleware, and parser.
- Content-based file validation.
- No user-controlled filesystem paths.
- Storage keys are generated from IDs and hashes.
- `.xlsx` decompression ratio, sheet, row, column, and cell limits.
- No macro-enabled workbook support.
- Formula policy is explicit.
- Chunk session expiry.
- Per-chunk and completed-file hash verification.
- Maximum concurrent public jobs per identifier.
- Resource ceilings for grid cells, timestamps, model candidates, search trials, SHAP samples, and video frames.
- Cancellation checks between major job stages.
- Temporary data deletion policy.

## 8.2 API security

- HTTPS only in production.
- Trusted-host and explicit CORS configuration.
- Stable error envelopes without traces.
- Correlation IDs.
- Request body limits.
- Parameterized SQL through SQLAlchemy.
- Signed or opaque artifact IDs.
- No arbitrary local path or object-store key accepted from clients.
- Job idempotency.
- Rate limiting for public job creation and contact.
- Security headers on frontend and API.
- Secrets only in deployment secret stores.
- Logs redact tokens, email bodies, file contents, connection strings, and object-store credentials.

## 8.3 Contact route

The contact route executes in the Next.js server runtime on Netlify:

1. Parse and normalize input with Zod.
2. Reject honeypot activation.
3. Verify Turnstile through the server-side Siteverify API.
4. Hash the network identifier with a server secret before using it as an Upstash key.
5. Apply sliding-window rate limits by network identifier and normalized email hash.
6. Use an idempotency key to prevent duplicate sends.
7. Send through Resend from a verified domain.
8. Escape user content in the email template.
9. Return a generic success response without exposing delivery internals.
10. Log only delivery ID, request ID, timestamp, and redacted sender hash.

Turnstile tokens are never accepted based only on client-side completion.

---

# 9. Testing plan

## 9.1 Backend tests

### Unit tests

- hashing and canonical serialization;
- schema versions and migrations;
- units and parameter aliases;
- timestamp ambiguity;
- coordinate transformation;
- duplicate resolution;
- each QC rule;
- boundary canonicalization;
- grid and mask alignment;
- IDW, RBF, kriging, and GP adapters;
- temporal interpolation gap rules;
- split generators;
- fold-local preprocessing;
- metrics and confidence intervals;
- model artifact compatibility;
- report bundle verification.

### Property tests

- hash stability;
- canonical JSON order invariance;
- unit conversion round trips;
- CRS transformation round trips within tolerance;
- no test index overlaps training index;
- time split never trains on later rows than test cutoff;
- spatial groups remain intact;
- interpolation never predicts outside the mask;
- migration sequence is idempotent at the target version.

### Scientific regression tests

Small deterministic fixtures establish expected numeric outputs with justified tolerances for:

- IDW surface;
- RBF surface;
- kriging prediction and variance;
- GP mean and standard deviation;
- linear and PCHIP temporal frames;
- grouped CV metrics;
- baseline performance;
- one Random Forest run;
- one XGBoost run;
- permutation importance;
- SHAP shape and additivity checks where supported.

### Integration tests

- upload session to completed raw artifact;
- ingestion to normalized Parquet;
- analysis job through worker;
- ML job through worker;
- cancellation;
- stale job recovery;
- object-store round trip;
- database migration from empty schema;
- export and verification;
- OpenAPI schema generation.

### API tests

- every route;
- invalid versions;
- invalid hashes;
- invalid ranges;
- missing chunks;
- idempotency conflicts;
- resource-limit rejection;
- stable error envelopes;
- artifact authorization and safe filenames.

## 9.2 Frontend tests

- form schemas;
- chunk retry and resume;
- API error handling;
- recipe validation;
- job polling lifecycle;
- observed/interpolated frame labels;
- map layer toggles;
- metric and uncertainty rendering;
- explanation limitations;
- contact token expiry and retry;
- keyboard operation;
- focus restoration;
- screen-reader labels.

## 9.3 E2E tests

Real backend, worker, PostgreSQL, and local object storage are started through Docker Compose. E2E tests do not mock the scientific API.

Required paths:

1. Upload valid wide CSV, map columns, finish ingestion, inspect QC.
2. Generate IDW and kriging outputs, inspect validation, switch timestamps, download map.
3. Generate an animation and verify MP4 download.
4. Train baselines, Random Forest, and XGBoost with station-group validation.
5. Inspect fold results and explanations.
6. Export a bundle and verify checksums through the CLI.
7. Resume an interrupted upload.
8. Reject malformed workbook and invalid boundary.
9. Cancel a running job.
10. Submit the contact form with service test credentials.

## 9.4 Coverage and quality gates

Backend:

- 90% line coverage overall.
- 95% for contracts, hashing, normalization, split generation, and compatibility.
- Ruff passes.
- MyPy strict passes for `src/`.
- Pytest passes.
- No prohibited stubs.
- Build wheel and import from installed wheel.
- OpenAPI snapshot current.

Frontend:

- TypeScript build passes.
- ESLint passes.
- Vitest passes.
- Critical utilities and forms at least 90% covered.
- Playwright passes on Chromium and one additional browser.
- Production build passes.
- Bundle-size limits pass.
- No client bundle contains server secrets.

---

# 10. GitHub workflow files

- `.github/workflows/backend-ci.yml`
  - Install from `uv.lock`, lint, type-check, test, coverage, wheel build, and installed-package import.
- `.github/workflows/frontend-ci.yml`
  - Install from `pnpm-lock.yaml`, contract generation check, lint, type-check, test, and build.
- `.github/workflows/contracts.yml`
  - Export OpenAPI, compare snapshot, regenerate TypeScript in check mode, validate examples, and run compatibility diff.
- `.github/workflows/integration.yml`
  - Start PostgreSQL and object storage, run migrations, API, worker, and backend integration tests.
- `.github/workflows/e2e.yml`
  - Start full stack and execute Playwright.
- `.github/workflows/security.yml`
  - Dependency audit, CodeQL, secret scan, Trivy container scan, and SBOM generation.
- `.github/workflows/reproducibility.yml`
  - Run the reference dataset twice and compare manifests, hashes, and declared numeric tolerances.
- `.github/workflows/release.yml`
  - Tag validation, changelog gate, backend image build, SBOM, provenance, and release artifacts.
- `.github/dependabot.yml`
  - Python, npm, GitHub Actions, and Docker updates grouped by ecosystem.
- `.github/CODEOWNERS`
  - Scientific-core, backend, frontend, contracts, and deployment review ownership.

Deployment is allowed only after CI. Netlify deploy previews may build every pull request, but production publishing must require the protected main branch.

---

# 11. Phase-by-phase implementation

## Phase 0 — Archive and freeze the prototype

Duration: half day.

Implement:

- Create a `legacy-prototype` tag or branch.
- Preserve the current archive and document its routes and known behavior.
- Extract the current default boundary and record source and license.
- Convert `Testfile.xlsx` into explicit test fixtures with documented expected interpretation.
- Write `docs/legacy-audit.md` listing useful behavior to preserve and code paths not to migrate.

Exit gate:

- Current implementation remains reproducible for comparison.
- No production code is copied without review.
- Default boundary provenance is known.

## Phase 1 — Monorepo, packaging, contracts, and CI foundation

Duration: one day.

Implement root files, backend package skeleton with functional configuration, frontend application shell, Docker Compose, first migration, contract version models, OpenAPI export, generated frontend types, lint/type/test configuration, and CI workflows.

Required functionality:

- Backend starts and passes readiness against PostgreSQL and object storage.
- Worker starts and can claim a test job.
- Frontend starts on Netlify Dev and can call backend health.
- Contact route is not implemented yet and is not displayed.
- All `__init__.py`, `py.typed`, `pyproject.toml`, `eslint.config.mjs`, lockfiles, and workflow files exist and are functional.

Exit gate:

- Clean clone installs reproducibly.
- Backend wheel builds and imports.
- Frontend production build passes.
- OpenAPI snapshot and generated TypeScript agree.
- Initial migration applies and rolls back.

## Phase 2 — Upload, parsing, normalization, hashing, and QC

Duration: two days.

Implement:

- storage adapters;
- upload sessions and chunks;
- browser chunked uploader;
- file validation;
- CSV/TSV, XLSX, and Parquet readers;
- layout detection and mapping UI;
- canonical domain models;
- parameter and unit registries;
- timestamp, coordinate, value, qualifier, unit, and duplicate normalization;
- canonical Parquet;
- QC rules;
- provenance and dataset version sealing;
- parse, normalization, and QC UI.

Exit gate:

- Long and wide fixtures produce the expected canonical rows.
- Interrupted uploads resume.
- All hashes verify.
- Malformed and oversized inputs fail safely.
- No raw value is overwritten.
- Dataset version can be downloaded and independently verified.

## Phase 3 — Jobs, worker, and versioned application services

Duration: one day, partly parallel with Phase 2.

Implement:

- durable job table;
- transactional claim;
- progress and cancellation;
- stale-job recovery;
- workflow context;
- service layer;
- job polling UI;
- idempotent job creation;
- artifact metadata and download.

Exit gate:

- API process performs no heavy scientific work.
- Worker restart does not lose job state.
- Cancellation is honored between stages.
- Repeated requests with the same idempotency key are safe.

## Phase 4 — Spatial, temporal, raster, and animation workflow

Duration: two days.

Implement:

- boundary validation;
- CRS transformation;
- grid and masking;
- IDW;
- RBF;
- ordinary kriging;
- Gaussian-process method;
- station and spatial-block validation;
- uncertainty/support surfaces;
- GeoTIFF and PNG output;
- global scale and legend;
- temporal alignment;
- linear and PCHIP interpolation;
- map UI;
- time controls;
- MP4 generation;
- analysis recipe UI.

Exit gate:

- Every spatial method passes scientific regression tests.
- Validation metrics exist before method comparison.
- Map uses backend artifacts and exact extent metadata.
- Animation uses stored surfaces and labels interpolated frames.
- No longitude/latitude planar-distance calculations remain.

## Phase 5 — ML, uncertainty, and explainability

Duration: two days.

Implement:

- task contract;
- feature builder;
- leakage-safe lags;
- baselines;
- preprocessing pipeline;
- split strategies;
- bounded search;
- Elastic Net, Random Forest, Extra Trees, histogram gradient boosting, and XGBoost adapters;
- outer evaluation;
- metrics and confidence intervals;
- bootstrap or quantile uncertainty;
- permutation importance;
- SHAP;
- stability analysis;
- ML frontend.

Exit gate:

- Baselines and candidate models use identical outer folds.
- Preprocessing is fold-local.
- Held-out stations, years, or spatial blocks are visible.
- Model artifact reload reproduces predictions within tolerance.
- Explainability payloads state model and data scope.
- No causal claim is generated.

## Phase 6 — Reporting, reproducibility, and publication export

Duration: one day.

Implement:

- methods record;
- metric, QC, prediction, and explanation tables;
- publication figures;
- run manifest;
- bundle creation;
- bundle verification;
- CLI reproduction;
- frontend export UI;
- reference reproducibility workflow.

Exit gate:

- A complete run exports one self-contained verified bundle.
- A clean environment can reproduce the reference run.
- Every output is traceable to dataset, boundary, recipe, code, and dependency hashes.
- Methods text matches actual executed settings.

## Phase 7 — Contact, Netlify, and security hardening

Duration: half to one day.

Implement:

- contact form;
- Turnstile widget and mandatory server verification;
- Upstash rate limits and idempotency;
- Resend email;
- privacy page;
- security headers;
- Netlify environment scopes;
- deployment contexts;
- container hardening;
- secret scanning;
- dependency and image scanning.

Exit gate:

- Contact cannot send without valid server-side Turnstile verification.
- Rate limits work without storing raw IP addresses.
- Secrets are absent from repository and client bundles.
- Production frontend deploys on Netlify.
- Backend and worker deploy from the same tested image.

## Phase 8 — Full E2E, documentation, and release candidate

Duration: one day.

Implement:

- full E2E suite;
- accessibility checks;
- performance budgets;
- deployment runbook;
- scientific methods and limitations;
- sample template files;
- changelog;
- release manifest;
- disaster and cleanup procedures;
- retention job for expired incomplete uploads and temporary artifacts.

Exit gate:

- All CI workflows pass.
- Full stack succeeds from clean clone.
- Reference analysis succeeds in production-like containers.
- Netlify deploy preview and production build pass.
- Release candidate contains no stubs, mocks, or undocumented scientific fallback.

---

# 12. One-to-two-week execution schedule

## Day 1

- Phase 0.
- Root structure.
- Backend `pyproject.toml`, package, `__init__.py`, `py.typed`.
- Frontend package, strict TypeScript, `eslint.config.mjs`.
- Docker Compose.
- PostgreSQL migration.
- Health, capabilities, OpenAPI, generated types.
- Base CI.

## Days 2–3

- Storage.
- Chunked upload.
- Parsers.
- Column mapping.
- Canonical models.
- Normalization.
- Hashing.
- QC.
- Dataset UI.

## Day 4

- Durable jobs.
- Worker.
- Services.
- Progress and cancellation.
- Artifact downloads.

## Days 5–6

- Boundary, CRS, grid, mask.
- IDW, RBF, kriging, GP.
- Validation.
- Raster outputs.
- Temporal interpolation.
- Map and animation.

## Days 7–8

- Feature builder.
- Baselines.
- Split strategies.
- scikit-learn models.
- XGBoost.
- Tuning and outer evaluation.
- Metrics, uncertainty, SHAP, permutation importance.
- ML UI.

## Day 9

- Reports.
- Methods record.
- Run manifests.
- Reproducibility bundle.
- CLI reproduce.
- Publication tables and figures.

## Day 10

- Turnstile, Upstash, Resend.
- Netlify configuration.
- Security headers.
- Production Docker.
- Integration and E2E.

## Days 11–12, when available

- Expand scientific regression fixtures.
- Add trend/change-point outputs.
- Improve subgroup diagnostics.
- Performance profiling.
- Accessibility.
- Documentation refinement.
- Production rehearsal.

The schedule assumes focused implementation and reuse of documented libraries rather than custom algorithm development. The scientific manuscript itself and final ecological interpretation are separate workstreams and will take longer than the software build.

---

# 13. Open-source model import policy

Use library implementations only when all of the following are true:

- active official documentation exists;
- license is compatible with the repository;
- package version is locked;
- estimator supports reproducible seeds where applicable;
- feature input and missing-value behavior are documented;
- serialized artifact can record library and version;
- wrapper can expose capability metadata;
- validation tests cover the adapter.

Approved initial sources:

- scikit-learn:
  - `Pipeline`
  - `ColumnTransformer`
  - `ElasticNet`
  - `RandomForestRegressor`
  - `ExtraTreesRegressor`
  - `HistGradientBoostingRegressor`
  - `GaussianProcessRegressor`
  - metrics and model-selection primitives
- XGBoost:
  - `XGBRegressor` through its scikit-learn-compatible interface
- SHAP:
  - `TreeExplainer` for supported tree estimators
- SciPy:
  - `RBFInterpolator`
  - interpolation and statistical primitives
- PyKrige:
  - `OrdinaryKriging`
- PyProj:
  - `Transformer`

Do not copy implementation files from external repositories. Add an adapter, record package version and configuration, cite the library in generated methods metadata, and test the adapter.

---

# 14. Performance and chunking limits

Initial configurable defaults:

- browser upload chunk: 5 MiB;
- upload concurrency: 3 parts;
- maximum file size: 100 MiB;
- CSV record batch: 50,000 rows;
- preview: first 200 valid rows plus stratified schema samples;
- maximum workbook sheets: 20;
- maximum workbook cells: 5,000,000;
- maximum unique timestamps per one interactive spatial run: 500;
- maximum grid cells per frame: 250,000;
- maximum animation frames: 900;
- maximum candidate models: 8;
- maximum search trials per model: 40;
- maximum SHAP explanation rows: configured sample, initially 2,000;
- API response tables are paginated;
- large tables and rasters are downloaded as artifacts rather than embedded in JSON.

Limits are included in capabilities and run manifests. Requests above limits are rejected with a structured error; they are not silently reduced.

---

# 15. Completion definition

The rebuild is complete when:

1. A new user can upload a valid long or wide environmental dataset.
2. The application verifies upload integrity.
3. The user can map columns and inspect parsing decisions.
4. The backend produces a canonical, hashed, versioned dataset.
5. QC findings are visible and no observations disappear silently.
6. The user can configure and run validated spatial interpolation.
7. The user can inspect prediction error and uncertainty.
8. The user can navigate observed and interpolated temporal surfaces.
9. The user can generate a verified MP4.
10. The user can define a defensible regression task.
11. Baselines and ML models are evaluated under the declared structured split.
12. The user can inspect fold metrics, uncertainty, permutation importance, and SHAP.
13. The user can export a complete, checksum-verified reproducibility bundle.
14. The CLI can reproduce the reference run.
15. Frontend and backend contracts are generated and version-checked.
16. Backend, frontend, integration, security, reproducibility, and E2E workflows pass.
17. Frontend deploys on Netlify.
18. Contact is protected by Turnstile and Upstash and delivered through Resend.
19. Scientific computation runs in the container backend and worker, not in Netlify Functions.
20. No production file contains a stub, mock scientific output, duplicate implementation, undocumented fallback, or placeholder execution branch.

---

# 16. Final implementation priority

The implementation order must remain:

1. contracts and reproducibility invariants;
2. storage and canonical ingestion;
3. normalization and QC;
4. durable jobs and workflow execution;
5. spatial and temporal science;
6. ML and explainability;
7. renderer-neutral results and exports;
8. frontend presentation;
9. contact and deployment hardening;
10. publication analysis.

Frontend pages may be built in parallel, but they must consume the real contracts and real API. They must not invent temporary scientific payloads that later become de facto interfaces.

The existing Quart application, direct session storage, duplicate animation modules, database table endpoint, and monolithic browser script should not be migrated. They are behavioral references only.
