# Changelog

All notable changes to Trendsmapp are recorded in this file. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Contract-visible changes are listed under their own heading because they affect
clients: an additive field inside `/api/v1` is backward compatible, while a
removed field, a changed meaning, or a new required request field requires a new
API major version.

## [Unreleased]

### Added

- Model-runs API (`/api/v1/model-runs`) and `train` worker job: ML tasks are
  validated against a sealed dataset version, executed with leakage-resistant
  fold-local preprocessing, and their metrics, per-fold results, held-out
  predictions, uncertainty intervals, and explanations are stored as
  content-addressed artifacts. Reposting a task is idempotent by task hash.
- Exports API (`/api/v1/exports`) and `export` worker job: one succeeded run
  becomes a deterministic, checksum-verified ZIP bundle (manifest, methods
  record, data dictionary, CSV tables, all run and dataset artifacts) that the
  bundle verifies itself before it is stored. The CLI gains
  `trendsmapp reproduce <bundle.zip>`, and `backend/scripts/reproduce_run.py`
  re-executes a bundle's recipe against the deployment database and compares
  every stored metric within a declared tolerance.
- Contact page and `/api/contact` route: Turnstile siteverify (mandatory
  server-side), HMAC-hashed IP/email sliding-window rate limits in Upstash,
  idempotent duplicate suppression, delivery through Resend, honeypot
  rejection, generic responses, and redacted logging. The route answers 503
  when the providers are not configured.
- Frontend model panel (task form, comparison table, per-fold metrics,
  uncertainty coverage, explanation importances) and export panel with the
  verified bundle download, wired into the dataset version explorer.
- Playwright E2E specs for the ML run + export flow and the contact form, plus
  a 72-row ML fixture.
- CI/release machinery: `integration.yml` (PostgreSQL + S3-compatible store,
  migrations up/down/up, full suite), `e2e.yml` (full-stack Playwright),
  `reproducibility.yml` (bundle determinism, verification, reproduction),
  `release.yml` (semver tag gate, changelog gate, contract checks, image
  build/push with provenance, Trivy scan, SBOM, GitHub release), and
  `CODEOWNERS`.
- Migration `0003_artifact_links`: artifact ownership moves to a many-to-many
  link table so content-addressed artifacts can be shared across runs without
  stealing the original run's linkage.

### Fixed

- CI checkouts now pull Git LFS objects (`lfs: true` on every
  `actions/checkout`), so the binary test fixtures (`*.xlsx`, `*.parquet`)
  are real files instead of pointer text on runners.
- `default_boundary.geojson` is renormalized to LF in the git index and its
  provenance digest re-recorded (`cba9aca4…`); the old blob was CRLF while
  `.gitattributes` forces `eol=lf`, so Linux CI checked out different bytes
  than the digest was recorded over and every boundary/QC/spatial check
  failed. New guard `scripts/check_text_normalization.py` (wired into the CI
  repository-invariants job) fails when any tracked file has CRLF in its index
  blob.
- CI: the integration job no longer pulls MinIO from Docker Hub (anonymous
  pulls are rate-limited); it runs a `moto[server]` S3 mock on port 5000 and
  creates the bucket with boto3. The backend-image smoke test starts the
  container with `--network host` so it reaches the runner's PostgreSQL. The
  backend image base moved to `python:3.13-slim-trixie` so the Trivy gate
  passes on a base without unfixed OS CVEs. The E2E job exports the
  `NEXT_PUBLIC_*`/origin variables at job level so `next build` inlines them
  regardless of webServer env timing.
- The legacy prototype's lint (pinned ruff 0.8.4) is clean again: import
  sorting, unused imports, whitespace, long-line wraps, a duplicated
  `ensure_prepared` definition, and a missing `from None` were fixed in the
  prototype tree. `scripts/verify_assets.py` records the committed blob digest
  of `ag-theme-alpine.css` (the old value matched no checkout), and the file
  is LF-normalized like every other tracked text file.
- The legacy prototype's untracked vendor bundle
  (`static/vendor/ag-grid-community/dist/…`) is force-tracked so the container
  image contains the assets `scripts/verify_assets.py` hashes; committed
  `backend/var/e2e-objects` junk is untracked (already gitignored).
- The legacy lint step is back to `ruff check .` — the root `ruff.toml`
  already `extend-exclude`s the rebuilt `backend`/`frontend`/`scripts` trees.
- CI: contract snapshot exporters now write LF-normalized bytes (the recorded
  digest differed between Windows and Linux runners); pytest gets
  `pythonpath = ["."]` so `uv run pytest` can import sibling `scripts`/`tests`
  packages; the backend image smoke test runs against PostgreSQL + local object
  store (the production image ships no dev-group aiosqlite); the E2E webServer
  backend command is cross-platform; MinIO is pinned to a release tag with a
  port-wait instead of an in-image healthcheck; trivy-action is pinned to a
  resolvable tag; the legacy workflow pins ubuntu-24.04 (Python 3.10), pulls
  Git LFS objects (the demo dataset is LFS, so its checksum verification failed
  on pointer files), passes a placeholder SECRET_KEY to the non-root container,
  and scopes its ruff run to the legacy tree only.
- `frontend/src/lib/env`: empty or whitespace-only environment variables are
  treated as unset (`readEnv`), so a blank Netlify variable can no longer fail
  schema validation and take down every page at module load.
- Netlify CSP now permits the Turnstile origins and cross-origin API images;
  `productionBrowserSourceMaps` is pinned off.

### Refactored (static-analysis findings)

- Cognitive-complexity hotspots split into helpers without behavior change:
  `propose_mapping` (54 → detection + long/wide proposers), `detect_layout`
  (43 → evidence collection + classification), `canonicalize_row` (39 →
  timestamp/value/depth helpers), `build_feature_frame` (39 → row selection,
  lag matrix, feature rows), `train_and_evaluate` (22 → per-fold candidate /
  baseline / aggregation helpers), `explain_model` (22 → per-method explainer
  table), `normalize_for_canonical` (22 → primitive/container split).
- Duplicated literals replaced by constants: `DATASET_VERSIONS_ID_REF`
  (persistence models), `HTTP_RESPONSE_START` (API middleware), `STATION_A` /
  `STATION_B` (CSV reader tests).
- `contracts.__all__` no longer exports the undefined name
  `"ArtifactSchemaMigrations"`.
- The NaN check in `serialization.py` uses `math.isnan` instead of
  `value != value`; raster nodata masks use `np.equal`/`np.not_equal`; IDW
  zero-distance tests use an epsilon comparison; sniffing confidence checks
  use `<= 0.0` — no float `==`/`!=` operators remain.
- Unused `current` assignment in `contracts/migrations.py` removed.
- Sync `tempfile.TemporaryFile()` in async worker code replaced by
  `trendsmapp/async_io.py` (`run_blocking` via `asyncio.to_thread` +
  `new_spool`), so blocking disk I/O stays off the event loop.
- Legacy `db.py` builds its TLS context with `ssl.create_default_context()`
  (Python 3.10+ secure defaults); hostname verification stays on for
  `verify-full`.

### Security

- No hardcoded credentials remain in tracked files. `docker-compose.yml` now
  refuses to start without `POSTGRES_*`/`MINIO_ROOT_*` set in `.env` (`:?`
  required-variable errors; no inline fallbacks). `.env.example` documents
  every variable for both stacks with placeholder values only, including the
  contact providers (Turnstile/Upstash/Resend), the S3 credentials, and the
  CI ephemeral placeholders. CI workflows source service credentials from
  repository variables with clearly-labeled ephemeral fallbacks, and the
  frontend contact tests use `test-…-not-real` fake tokens. Backend settings
  keep credentials as `SecretStr` with no defaults.

### Dependencies

- pyarrow 21 → 26 (fixes PYSEC-2026-113), fastapi 0.141 → 0.162, pytest 9.1 →
  9.2, pytest-asyncio 1.4.1.post1, python-multipart 0.0.33, typing-inspection
  0.4.5; frontend @tanstack/react-query 5.105.1 and @types/node 26.6.6; all
  GitHub Actions bumped to current majors. ESLint 10 / TypeScript 7 majors and
  the legacy Docker base image are ignored in `dependabot.yml` until the
  toolchain supports them.

- Artifact registration no longer loses run/version ownership when identical
  bytes are registered again; `list_for_run`/`list_for_version` join through
  `artifact_links` (previously a re-run with identical raster bytes listed no
  artifacts of its own and animation export failed).
- `services/model_training.py` imported its artifact-id constructor, stored
  artifacts under the allowed `runs/` key prefix, attached the job id to the
  run row, and now computes the uncertainty stage it previously skipped.

### Contract-visible

- Added `/api/v1/model-runs` (POST, GET run/metrics/folds/predictions/
  explanations/artifacts) and `/api/v1/exports` (POST, GET, download) under
  `/api/v1`; the OpenAPI snapshot, `contracts/COMPATIBILITY.md`, and the
  generated frontend types were regenerated.

- Chunked upload API and service: session creation with a validated part plan,
  per-part range, size, and digest verification, content-addressed assembly of
  the immutable raw artifact, idempotent completion that enqueues the ingest
  job, and abort with part cleanup.
- Dataset API: probe of a stored upload, dataset and version creation from a
  confirmed column mapping, version listing and detail with artifacts, preview,
  stored parse/normalization/QC reports, provenance, and artifact download.
- Worker ingest workflow: probe-only jobs at upload completion and full
  parse → normalize → QC → artifact → seal jobs at dataset creation, with
  progress stages, cancellation probes, station/parameter registration, and
  provenance events. The CLI gains a `dev` command that migrates, serves, and
  polls in one process.
- Frontend ingest UI: chunked uploader with retry and progress, probe view,
  mapping editor, dataset list and version explorer with preview, reports,
  provenance, and artifact downloads; typed client extended with POST/PUT and
  ingest contract schemas; generated contract types refreshed from the new
  OpenAPI snapshot.
- Contract artifacts under `contracts/`: the generated OpenAPI snapshot, the
  generated schema-version document, the committed payload examples, and a
  compatibility note that pins the digest of the snapshot it describes.
- Repository verification scripts: a placeholder scan for the production paths,
  a deterministic lockfile-hash recorder, a contract-example verifier that
  compares the committed payloads with the running API, and a compatibility-note
  checker.
- Next.js frontend application with a typed API client, runtime contract
  schemas validated with Zod, a server-rendered live service status, the
  methods and privacy pages, error boundaries, and the generated contract types
  produced from the OpenAPI snapshot.
- Container image for the backend with a frozen dependency install, an
  unprivileged runtime user, and a liveness health check.
- CI workflows for the rebuilt stack: lint, type check, tests with the coverage
  gate, contract drift, the placeholder scan, the lockfile-hash check, a
  container scan, a bill of materials, and a secret scan. The verification of
  the frozen prototype moved to its own workflow.
- Developer tooling: a `Makefile` with stable commands, a pre-commit
  configuration, and a Dependabot configuration.
- Documentation: architecture, data contract, reproducibility, deployment, and
  publication workflow, next to the legacy audit and the scientific-method
  reference.

### Fixed

- Alembic now uses the current `path_separator` configuration key instead of
  the deprecated `version_path_separator`.

## [0.1.0] - 2026-10-27

The first release of the rebuilt application. It establishes the foundation on
which the scientific pipeline is built: versioned contracts, content-addressed
storage, a durable job queue, and a container-ready backend.

### Added

- Monorepo layout with an independent `backend/` (Python 3.13, FastAPI, uv) and
  `frontend/` (Next.js App Router, pnpm) application.
- Versioned contracts: API major version, artifact schema version, recipe schema
  version, and a pure sequential migration registry for stored documents.
- Canonical hashing and serialization helpers: streaming SHA-256, canonical JSON
  with sorted keys and finite numbers, and constant-time digest comparison.
- Domain layer with the canonical observation model, typed identifiers, unit
  registry with dimension-checked conversion, and explicit duplicate, exclusion,
  censoring, and extrapolation policies.
- Persistence layer with thirteen tables, an Alembic migration that applies and
  rolls back, and repositories for datasets, uploads, jobs, runs, artifacts, and
  registries.
- Object-store adapters: an atomic local filesystem store and an S3-compatible
  store that records and verifies the SHA-256 of every object.
- Worker process that claims jobs transactionally, records progress, supports
  cancellation, and recovers jobs abandoned by a lost worker.
- Public API surface under `/api/v1`: liveness, readiness, capabilities, contract
  versions, and the generated OpenAPI document.
- Stable error envelope with machine-readable codes and correlation identifiers.
- Local developer stack in `docker-compose.yml` with PostgreSQL, an S3-compatible
  object store, the API, and the worker.

### Changed

- The prototype application at the repository root is frozen. It remains as a
  behavioral reference and is documented in `docs/legacy-audit.md`. It is not
  deployed and no production code was copied from it.

### Security

- The `.secret` file that was tracked in the prototype is no longer part of the
  build inputs; secrets belong in the deployment secret store.

[Unreleased]: https://github.com/OWNER/REPOSITORY/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/OWNER/REPOSITORY/releases/tag/v0.1.0
