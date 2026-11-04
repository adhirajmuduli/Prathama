# Architecture of the rebuilt Trendsmapp

This document describes the rebuilt application. The frozen prototype at the
repository root is documented separately in `docs/legacy-audit.md`; it is kept
as a behavioral reference and receives no new features.

## 1. Topology

```
browser ──HTTPS──> Netlify ──> frontend/ (Next.js App Router)
                             └──HTTPS──> backend/ API (FastAPI, container)
                                              │
                                              ├──PostgreSQL (runs, uploads, datasets, artifacts)
                                              └──Object store (raw uploads, artifacts)
                                              │
                                        backend/ worker (same image, different command)
```

* The frontend is the public deployment. It never performs scientific
  computation; it renders the published contract and the live status of the
  backend.
* The backend API validates and delegates. It owns the request boundary, the
  contract, the session factory, and the object store handle.
* The worker owns the science. It polls the job table with transactional row
  locking, executes ingestion, analysis, and export jobs, and writes every
  output to the object store.
* PostgreSQL is the system of record for state that must be queried (jobs,
  runs, datasets, artifact references, registries). The object store holds the
  bytes: raw uploads and artifacts, addressed by content.

## 2. Repository map

| Path | Responsibility |
| --- | --- |
| `backend/src/trendsmapp/api/` | Application factory, routers, middleware, dependency providers, error handlers |
| `backend/src/trendsmapp/contracts/` | Contract versions, shared models, error envelope, compatibility rules, schema migrations |
| `backend/src/trendsmapp/domain/` | Canonical observation model, identifiers, units, enumerations, policies, provenance |
| `backend/src/trendsmapp/persistence/` | Engine and session factory, ORM models, repositories |
| `backend/src/trendsmapp/storage/` | Object store protocol, local and S3 adapters, key validation |
| `backend/src/trendsmapp/services/` | Application services that coordinate persistence and storage |
| `backend/src/trendsmapp/worker/` | Queue polling, job lifecycle, heartbeat, handler registry |
| `backend/src/trendsmapp/hashing.py` | Canonical hashing of streams and files |
| `backend/src/trendsmapp/serialization.py` | Canonical JSON serialization |
| `backend/src/trendsmapp/logging_config.py` | Structured logging with secret redaction |
| `backend/src/trendsmapp/settings.py` | Validated process configuration |
| `backend/migrations/` | Alembic migration history; the schema owner |
| `backend/scripts/` | OpenAPI and schema-version exporters used by CI |
| `frontend/src/app/` | Next.js App Router routes, layouts, and error boundaries |
| `frontend/src/lib/` | Typed API client, runtime contract schemas, environment validation, formatting |
| `contracts/` | OpenAPI snapshot, schema versions, committed payload examples, compatibility note |
| `scripts/` | Repository-wide checks: placeholder scan, lockfile hashes, contract verification |
| `docs/` | Architecture, data contract, reproducibility, deployment, publication workflow, legacy audit |

## 3. Request path

1. `RequestContextMiddleware` assigns a request identifier and records the
   start time.
2. `SecurityHeadersMiddleware` adds the hardening headers to every response.
3. `BodyLimitMiddleware` rejects a body larger than the configured ceiling
   before it is parsed.
4. `TrustedHostMiddleware` and `CORSMiddleware` enforce the host and origin
   policy.
5. The route handler validates the request with the contract models and
   delegates to an application service.
6. `install_exception_handlers` converts a domain error into the single error
   envelope: `error.code`, `error.message`, optional `error.details`, and
   `request_id`.

No route handler performs scientific computation, and no route handler opens a
database session of its own: sessions come from the dependency provider.

## 4. Worker path

1. The worker claims a job with `SELECT ... FOR UPDATE SKIP LOCKED`, so two
   workers never process the same job.
2. The handler resolves the job kind through the handler registry. A kind
   without a registered handler fails the job with a structured `job_error`;
   it is never silently ignored.
3. Progress is written to the job row while the job runs. The heartbeat keeps
   the lease alive so that a stalled job is detected instead of blocking the
   queue forever.
4. The terminal state is `succeeded` or `failed`. A failure records the error
   code, the message, and the details.
5. Every artifact is written to the object store first and registered in
   PostgreSQL afterwards, so the database never references bytes that do not
   exist.

## 5. Invariants

* Raw uploads are immutable. A transformation produces a new artifact; it
  never rewrites the input.
* Raw values are never overwritten. Normalization adds units, timestamps, and
  identifiers beside the original value.
* Every stored object and every artifact carries a SHA-256 digest of its exact
  bytes.
* Quality control produces flags, never silent deletions.
* Preprocessing is fitted inside the training fold.
* Spatial mathematics happens in a projected coordinate system.
* An unknown major contract version is rejected; an unknown minor version is
  accepted and recorded.
* A capability is announced only when the code path exists and is exercised by
  tests. `services/capabilities.py` is the single source of that truth.
* No production path contains a placeholder branch. `scripts/check_no_stubs.py`
  fails the build when one appears.

## 6. Trust boundaries

| Boundary | Rule |
| --- | --- |
| Browser to API | Body size ceiling, explicit allowed origins, trusted host list, request identifier per call |
| API to database | Single session factory, transactions that roll back on failure, migrations owned by Alembic |
| API and worker to object store | Content-addressed keys, key path validation, atomic writes, size verification |
| Job to handler | Only a registered handler may run; the payload is validated against the recipe schema version |
| Frontend to API | Zod validation of every response, timeout and cancellation on every request, no secret in browser code |

## 7. Contract flow

```
contracts/openapi.v1.json ──> frontend/src/lib/contracts/generated.ts
        │                                   │
        └──> frontend/src/lib/contracts/runtime.ts (hand-written runtime schemas)
```

The OpenAPI snapshot is exported from the code, committed, and verified in CI.
The frontend types are generated from that snapshot and are never edited by
hand. CI fails when the snapshot changes without a regenerated frontend
contract and an updated compatibility note.

## 8. Current implementation state

The rebuild is delivered in phases. The current build implements the
foundation: the API surface, the contract layer, the persistence layer, the
object stores, the job queue, the worker lifecycle, and the frontend shell
that renders the live service status.

The scientific pipelines — ingestion of uploaded datasets, normalization,
quality control, spatial interpolation, temporal animation, model training,
explainability, and export — are not implemented yet. The backend announces
none of them in its capability document, and the frontend does not offer a
control that cannot work.
