# Trendsmapp backend

FastAPI + worker backend for the Trendsmapp rebuild. The package owns every
scientific computation; the Next.js frontend in `../frontend` never performs
interpolation, quality control, normalization, or model fitting.

The authoritative architecture, invariants, and phase gates are defined in
[`../trendsmapp_rebuild_and_publication_grade_plan.md`](../trendsmapp_rebuild_and_publication_grade_plan.md).
The frozen legacy prototype is documented in
[`../docs/legacy-audit.md`](../docs/legacy-audit.md).

## Layout

| Path | Responsibility |
|---|---|
| `src/trendsmapp/contracts/` | Versioned request/response contracts, error envelopes, compatibility rules, schema migrations. |
| `src/trendsmapp/domain/` | Scientific meaning: observations, stations, parameters, units, policies, provenance. |
| `src/trendsmapp/ingestion/` | File-type detection and format readers (CSV/TSV, XLSX, Parquet). |
| `src/trendsmapp/normalization/` | Timestamps, coordinates, values, units, duplicates, canonical Parquet. |
| `src/trendsmapp/qc/` | Explicit quality-control rules that flag rather than delete. |
| `src/trendsmapp/geospatial/` | CRS handling, boundary canonicalization, grids, masks, sectors. |
| `src/trendsmapp/spatial/` | IDW, RBF, ordinary kriging, Gaussian process, validation, rasters. |
| `src/trendsmapp/temporal/` | Alignment, interpolation without default extrapolation, seasons, trends. |
| `src/trendsmapp/features/` | Leakage-safe feature construction with lineage. |
| `src/trendsmapp/ml/` | Baselines, estimators, fold-local preprocessing, splits, metrics, artifacts. |
| `src/trendsmapp/explainability/` | Permutation importance, SHAP, stability. |
| `src/trendsmapp/visualization/` | Scales, palettes, heatmaps, legends, figures, MP4 animation. |
| `src/trendsmapp/reporting/` | Tables, methods record, run manifest, export bundle, verification. |
| `src/trendsmapp/storage/` | Content-addressed object-store protocol with local and S3 adapters. |
| `src/trendsmapp/persistence/` | SQLAlchemy ORM tables and repositories (PostgreSQL in production). |
| `src/trendsmapp/services/` | Application services used by both the API and the worker. |
| `src/trendsmapp/workflows/` | End-to-end job handlers (ingest, analyze, train, animate, export). |
| `src/trendsmapp/api/` | FastAPI app factory, middleware, routers, error mapping. |
| `src/trendsmapp/worker/` | PostgreSQL-backed job claiming, heartbeats, stale-job recovery. |
| `src/trendsmapp/cli/` | `trendsmapp` command line entry point. |

Every `__init__.py` contains exports and package metadata only: importing a
package never opens a database connection, reads environment variables, or
performs scientific work.

## Requirements

- Python 3.13
- [uv](https://docs.astral.sh/uv/) for lockfile-driven installs
- PostgreSQL 15+ and an S3-compatible bucket for production
- FFmpeg on `PATH` for MP4 encoding (the `imageio-ffmpeg` wheel bundles a
  static binary for development and CI)

## Setup

```bash
cd backend
uv sync --python 3.13
uv run trendsmapp version
```

`uv.lock` is the authoritative dependency resolution. `pyproject.toml` holds
only configuration; there is no authoritative `requirements.txt`.

## Run

```bash
# API
uv run uvicorn trendsmapp.api.app:create_app --factory --host 127.0.0.1 --port 8000

# Worker (separate process, same image)
uv run trendsmapp worker

# Export the OpenAPI snapshot used by contract CI
uv run python scripts/export_openapi.py ../contracts/openapi.v1.json
```

Local development uses the local object-store adapter and SQLite; production
uses the S3 adapter and PostgreSQL. The choice is made by
`TRENDSMAPP_OBJECT_STORE_BACKEND` and `TRENDSMAPP_DATABASE_URL`.

## Migrations

```bash
uv run alembic upgrade head
uv run alembic downgrade base
```

`migrations/versions/0001_initial.py` creates the metadata, job, registry,
run, and artifact tables. The migration is the only way the schema changes;
the application never calls `create_all`.

## Quality gates

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest --cov
```

Coverage must stay at or above 90% overall, with 95% for contracts, hashing,
normalization, split generation, and compatibility.

## Configuration

All settings use the `TRENDSMAPP_` prefix and are validated at process start.
See `../.env.example` for the full list. Production startup fails fast when
the object store is not S3-compatible, when the database is not PostgreSQL, or
when a shared secret is missing.
