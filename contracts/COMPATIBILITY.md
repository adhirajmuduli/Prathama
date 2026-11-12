# Contract compatibility

This file records the contract changes of the rebuilt API. Every change to the
OpenAPI snapshot must appear here with its reason, so a reviewer can judge
whether the change is compatible.

The digest below pins the snapshot that this note describes. CI fails when the
snapshot changes without an updated note.

OpenAPI snapshot SHA-256: `4962474e5b5bf897915eeb231ac495ee9b2ac53d6d215608589a6b291268be82`

The digest is computed over the LF-normalized bytes: the exporter writes bytes
directly so the snapshot is identical on Windows and Linux runners.

## API major version 1

The first published contract of the rebuilt API.

### Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/v1/health/live` | Liveness of the process. Never touches the database or the object store. |
| GET | `/api/v1/health/ready` | Readiness of the process, including the database and the object store. Answers `503` when a dependency is unavailable. |
| GET | `/api/v1/capabilities` | The formats, methods, model families, versions, limits, and configuration of this deployment. |
| GET | `/api/v1/contracts/versions` | The contract versions this deployment speaks. |
| POST | `/api/v1/uploads` | Create a chunked upload session and return its part plan. |
| GET | `/api/v1/uploads/{upload_id}` | The state of an upload session, including received and missing parts. |
| PUT | `/api/v1/uploads/{upload_id}/parts/{part_number}` | Store one part, validated against its declared range and size. |
| POST | `/api/v1/uploads/{upload_id}/complete` | Assemble, verify, and store the raw upload, then enqueue the ingest job. |
| POST | `/api/v1/uploads/{upload_id}/abort` | Cancel an open session and delete its stored parts. |
| GET | `/api/v1/jobs/{job_id}` | One durable job as seen by a client. |
| POST | `/api/v1/jobs/{job_id}/cancel` | Request cancellation of a queued or running job. |
| POST | `/api/v1/uploads/{upload_id}/probe` | Describe the first rows of a completed upload and propose a mapping. |
| POST | `/api/v1/datasets` | Create a dataset version from an upload and a confirmed mapping, and enqueue the ingest job. |
| GET | `/api/v1/datasets` | A page of datasets, most recently updated first. |
| GET | `/api/v1/datasets/{dataset_id}` | One dataset with its current version. |
| GET | `/api/v1/datasets/{dataset_id}/versions` | Every version of a dataset, oldest first. |
| GET | `/api/v1/dataset-versions/{version_id}` | One dataset version with its artifacts. |
| GET | `/api/v1/dataset-versions/{version_id}/preview?limit=` | The first rows of a normalized dataset version. |
| GET | `/api/v1/dataset-versions/{version_id}/reports/{kind}` | One stored JSON report (`parse`, `normalization`, `qc`). |
| GET | `/api/v1/dataset-versions/{version_id}/provenance` | The provenance events of a dataset version. |
| GET | `/api/v1/artifacts/{artifact_id}` | One artifact reference. |
| GET | `/api/v1/artifacts/{artifact_id}/content` | Stream the bytes of one stored artifact. |
| POST | `/api/v1/analyses` | Validate a recipe against a sealed dataset version and enqueue the analysis job. |
| GET | `/api/v1/analyses/{run_id}` | One analysis run with its recipe and hashes. |
| GET | `/api/v1/analyses/{run_id}/artifacts` | Every artifact a run produced. |
| GET | `/api/v1/analyses/{run_id}/results` | The stored results document of a run. |
| POST | `/api/v1/analyses/{run_id}/animations` | Enqueue an animation job over the run's stored rasters. |
| POST | `/api/v1/model-runs` | Validate an ML task against a sealed dataset version and enqueue the training job. The task hash is the idempotency key. |
| GET | `/api/v1/model-runs/{run_id}` | One model run with its task, results, explanations, artifacts, and warnings. |
| GET | `/api/v1/model-runs/{run_id}/metrics` | The stored metrics document of a model run (aggregated, per-family, uncertainty). |
| GET | `/api/v1/model-runs/{run_id}/folds` | The per-fold metrics of every evaluated family. |
| GET | `/api/v1/model-runs/{run_id}/predictions` | The held-out observed-versus-predicted table of a model run. |
| GET | `/api/v1/model-runs/{run_id}/explanations` | The stored explanations document (importance rows and recorded limitations). |
| GET | `/api/v1/model-runs/{run_id}/artifacts` | Every artifact a model run produced (`model`, `metrics`, `predictions`, `explanations`). |
| POST | `/api/v1/exports` | Enqueue the export of one succeeded run as a checksum-verified bundle. Idempotent per run. |
| GET | `/api/v1/exports/{export_id}` | One export with its `export_bundle` artifact and the manifest inside the bundle. |
| GET | `/api/v1/exports/{export_id}/download` | Stream the verified ZIP bundle with its SHA-256 header. |
| POST | `/api/v1/reports` | Enqueue the PDF report of one succeeded run. Idempotent per run. |
| GET | `/api/v1/reports/{report_id}` | One report with its `report` PDF artifact and summary. |
| GET | `/api/v1/reports/{report_id}/download` | Stream the rendered PDF report with its SHA-256 header. |

### Conventions

* Every response carries `X-Request-ID`.
* Every error response uses the envelope `error.code`, `error.message`,
  optional `error.details`, and `request_id`.
* The error codes are `validation_error`, `not_found`, `conflict`,
  `resource_limit_exceeded`, `unsupported_media_type`, `payload_too_large`,
  `method_not_allowed`, `unauthorized`, `forbidden`, `rate_limited`,
  `internal_error`, `service_unavailable`, and `job_error`.
* An additive field inside an existing response is compatible. A removed or
  renamed field, a changed unit, a changed meaning, and a changed error code
  are not, and require a new API major version.

### Compatibility rules

* A request that declares an unsupported major version is rejected with
  `409` and a structured reason.
* An unsupported minor version is accepted, and the applied version is recorded
  in the run manifest.
* A consumer ignores unknown fields in a response.
* A schema change is applied one version at a time by a deterministic migration
  function in `backend/src/trendsmapp/contracts/migrations.py`.
