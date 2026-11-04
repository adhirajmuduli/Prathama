# Trendsmapp

Trendsmapp is a publication-grade web application for environmental monitoring
data: chunked upload and integrity verification, canonical normalization with
preserved raw values, explicit quality control, validated spatial and temporal
analysis, leakage-resistant machine learning, and checksum-verified export
bundles.

The repository is a monorepo. The scientific work runs in a containerized
Python backend and a separate worker process; the public web application is a
Next.js frontend deployed on Netlify. The frontend never performs scientific
computation: it renders artifacts produced by the backend.

## Current state

This repository is under active rebuild, phase by phase, following
[`trendsmapp_rebuild_and_publication_grade_plan.md`](trendsmapp_rebuild_and_publication_grade_plan.md).

**Implemented now (phase 1 — foundation):**

- versioned API, artifact-schema, and recipe contracts with a pure migration
  registry for stored documents;
- canonical hashing and serialization, including streaming SHA-256 and canonical
  JSON;
- the canonical observation domain model, typed identifiers, a dimension-checked
  unit registry, and explicit duplicate, exclusion, censoring, and
  extrapolation policies;
- thirteen database tables with an Alembic migration that applies and rolls back;
- content-addressed object storage with an atomic local adapter and an
  S3-compatible adapter that verifies every stored digest;
- a durable job table with transactional claiming, progress, cancellation, and
  recovery of jobs abandoned by a lost worker;
- the public API surface under `/api/v1`: liveness, readiness, capabilities,
  contract versions, and the OpenAPI document;
- a Next.js application shell that reports the live backend status.

**Not implemented yet.** Uploads, parsing, normalization, quality control,
spatial interpolation, temporal animation, machine learning, explainability,
and export bundles are specified in the rebuild plan and are not present in this
release. The backend reports exactly what it supports through
`GET /api/v1/capabilities`; the capabilities list is empty until those layers
land. Nothing in the interface implies a capability the backend does not have.

The prototype application at the repository root is **frozen**. It is retained
as a behavioral reference and documented in
[`docs/legacy-audit.md`](docs/legacy-audit.md). It is not deployed, and no
production code was copied from it.

## Repository layout

| Path | Purpose |
|---|---|
| `backend/` | FastAPI application, worker, domain layers, persistence, and storage |
| `frontend/` | Next.js App Router application deployed on Netlify |
| `contracts/` | Generated OpenAPI snapshot, schema versions, and contract examples |
| `docs/` | Architecture, data contract, methods, reproducibility, and deployment notes |
| `scripts/` | Repository-level verification scripts |
| `tests/`, `app.py`, `routes/`, `utils/` | Frozen prototype and its tests |

## Architecture

```
browser ──► Next.js (Netlify) ──► FastAPI API (/api/v1) ──► PostgreSQL
                    │                      │
                    │                      ├──► S3-compatible object store
                    │                      │
                    └──────────────► worker process (same image) ──► artifacts
```

The API process validates requests, writes rows, and returns identifiers. It
never performs scientific computation. The worker claims one job at a time
using `FOR UPDATE SKIP LOCKED`, executes it, and records progress, completion,
failure, and cancellation.

Design rules that the code enforces:

- raw uploads are immutable and raw values are never overwritten;
- every artifact is addressed by the SHA-256 of its exact bytes;
- every transformation produces a new artifact and a provenance event;
- missing, invalid, censored, and excluded values stay distinguishable;
- quality-control flags never delete observations;
- spatial calculations use projected coordinates, never degrees;
- model preprocessing is fitted inside the training fold;
- unknown major contract versions are rejected.

## Local development

Requirements: Python 3.13, [uv](https://docs.astral.sh/uv/), Node.js 22,
pnpm 11, and Docker for the full local stack.

```bash
make install          # install backend and frontend dependencies from the lockfiles
make test             # run both test suites
make lint typecheck   # run Ruff, ESLint, MyPy, and TypeScript
make coverage         # backend suite with the coverage gate
make up               # PostgreSQL, object store, API, and worker
```

Backend only:

```bash
cd backend
uv sync --frozen --all-groups
uv run uvicorn trendsmapp.api.app:create_app --factory --reload --port 8000
uv run trendsmapp worker
```

The API is then available at `http://127.0.0.1:8000/api/v1`, with the OpenAPI
document at `http://127.0.0.1:8000/api/v1/openapi.json`.

## Configuration

Copy [`.env.example`](.env.example) to `.env`. Every backend variable uses the
`TRENDSMAPP_` prefix and is validated at startup; a production process refuses
to start without PostgreSQL, an S3-compatible object store, explicit CORS
origins, and explicit trusted hosts. Secrets belong in the deployment secret
store, never in the repository.

## Contracts

The backend exports its OpenAPI document to
[`contracts/openapi.v1.json`](contracts/openapi.v1.json), and the frontend
generates its TypeScript types from that snapshot. CI fails when the snapshot
drifts from the code.

```bash
make contracts        # export and verify the contract snapshot
```

Compatibility rules, the canonical observation model, and the versioning
procedure are documented in [`contracts/README.md`](contracts/README.md). Every
contract change is recorded in
[`contracts/COMPATIBILITY.md`](contracts/COMPATIBILITY.md), which also pins the
digest of the snapshot it describes.

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — components and data flow
- [`docs/data-contract.md`](docs/data-contract.md) — canonical observation semantics
- [`docs/scientific-methods.md`](docs/scientific-methods.md) — methods and their limits
- [`docs/reproducibility.md`](docs/reproducibility.md) — hashes, seeds, and manifests
- [`docs/deployment.md`](docs/deployment.md) — Netlify and container deployment
- [`docs/publication-workflow.md`](docs/publication-workflow.md) — freezing, running, and exporting a study
- [`docs/legacy-audit.md`](docs/legacy-audit.md) — frozen prototype audit

## License

Code is released under the [MIT License](LICENSE). Dataset reuse rights must be
documented separately; see [`examples/README.md`](examples/README.md) for the
provenance of the bundled workbook.
