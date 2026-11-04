# Contract compatibility

This file records the contract changes of the rebuilt API. Every change to the
OpenAPI snapshot must appear here with its reason, so a reviewer can judge
whether the change is compatible.

The digest below pins the snapshot that this note describes. CI fails when the
snapshot changes without an updated note.

OpenAPI snapshot SHA-256: `2d37f8508428b640be40276e5b14250c121667a2c11064df316cf6b0dbe0c2cd`

## API major version 1

The first published contract of the rebuilt API.

### Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/v1/health/live` | Liveness of the process. Never touches the database or the object store. |
| GET | `/api/v1/health/ready` | Readiness of the process, including the database and the object store. Answers `503` when a dependency is unavailable. |
| GET | `/api/v1/capabilities` | The formats, methods, model families, versions, limits, and configuration of this deployment. |
| GET | `/api/v1/contracts/versions` | The contract versions this deployment speaks. |

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
