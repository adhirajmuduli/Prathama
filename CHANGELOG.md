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
