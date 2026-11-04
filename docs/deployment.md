# Deployment

The deployment has two independent parts: a public frontend on Netlify and a
containerized backend. They are deployed separately and share only the HTTP
contract.

```
                     ┌───────────────────────────┐
  browser ──HTTPS──▶ │ Netlify: frontend/        │
                     │ Next.js App Router        │
                     └────────────┬──────────────┘
                                  │ HTTPS (server-side calls and
                                  │ browser refreshes)
                     ┌────────────▼──────────────┐
                     │ API container             │
                     │ trendsmapp.api.app        │
                     └────────────┬──────────────┘
                          ┌───────┴────────┐
                          ▼                ▼
                    PostgreSQL      Object storage (S3)
                          ▲                ▲
                          └──── worker ───┘
```

The worker runs the same image as the API with a different command. The
frontend never executes scientific code.

## 1. Frontend on Netlify

The configuration lives in `netlify.toml` at the repository root:

| Setting | Value | Reason |
| --- | --- | --- |
| `base` | `frontend` | The application lives in its own directory |
| `command` | `pnpm run build` | The lockfile fixes the exact dependency graph |
| `NODE_VERSION` | `22.17.0` | The version the lockfile and the engines field require |
| `PNPM_VERSION` | `11.22.0` | The version declared in `package.json` |

Netlify provisions the Next.js adapter automatically; no adapter version is
pinned, so the platform keeps it compatible with the Next.js release in use.

### Environment variables

Set these in the Netlify site configuration, for production and for the deploy
preview context:

| Variable | Purpose |
| --- | --- |
| `BACKEND_API_ORIGIN` | Origin of the API used for server-side rendering |
| `NEXT_PUBLIC_API_BASE_URL` | Origin of the API used by browser refreshes; empty disables them |
| `NEXT_PUBLIC_SITE_URL` | Public origin of the site, used for the sitemap and the canonical URL |

No secret belongs in the frontend. The server-only environment module is
protected by an ESLint import boundary, so a secret cannot be read by browser
code by accident.

### Headers and redirects

The security headers are declared in `netlify.toml` and are applied to every
response: `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`,
`Permissions-Policy`, `Strict-Transport-Security`, and a content security
policy that allows only same-origin scripts and styles plus HTTPS connections.
A future `/api/*` route handler answers with `Cache-Control: no-store`.

## 2. Backend container

The image is built from `backend/Dockerfile`:

* a builder stage resolves the dependencies from `backend/uv.lock` with
  `uv sync --frozen`, so the image contains exactly the locked versions;
* a runtime stage copies the virtual environment, the migrations, and the
  Alembic configuration, and runs as the unprivileged user `trendsmapp`
  (UID 10001);
* `PYTHONHASHSEED=0` keeps the interpreter deterministic across restarts;
* the health check probes the liveness endpoint, which does not depend on the
  database or the object store.

Build and push the image from the repository root:

```bash
docker build -t registry.example.org/trendsmapp/backend:0.1.0 backend
docker push registry.example.org/trendsmapp/backend:0.1.0
```

### Required configuration

| Variable | Reason |
| --- | --- |
| `TRENDSMAPP_ENVIRONMENT` | `production` in a deployment |
| `TRENDSMAPP_DATABASE_URL` | A PostgreSQL URL; production refuses any other database |
| `TRENDSMAPP_OBJECT_STORE_BACKEND` | `s3` in production |
| `TRENDSMAPP_S3_BUCKET`, `TRENDSMAPP_S3_ENDPOINT_URL`, `TRENDSMAPP_S3_REGION` | The object store |
| `TRENDSMAPP_S3_ACCESS_KEY_ID`, `TRENDSMAPP_S3_SECRET_ACCESS_KEY` | The object store credentials |
| `TRENDSMAPP_CORS_ALLOW_ORIGINS` | The public frontend origin |
| `TRENDSMAPP_TRUSTED_HOSTS` | The public hostnames of the API |

The settings model refuses to start a production process with an insecure
configuration: a local object store, a SQLite database, an empty origin list,
or an empty host list is an error, not a warning.

### Processes

| Process | Command |
| --- | --- |
| Migration | `alembic upgrade head` |
| API | `uvicorn trendsmapp.api.app:create_app --factory --host 0.0.0.0 --port 8000` |
| Worker | `trendsmapp worker` |

The migration runs once per deployment, before the API and the worker start.
The API and the worker are stateless and may run in several replicas; the
worker claims jobs with row locking, so a job is executed exactly once.

## 3. Local stack

`docker-compose.yml` starts PostgreSQL, an S3-compatible object store, the
migration, the API, and the worker:

```bash
make up      # docker compose up --build
make logs    # docker compose logs --tail=100 -f
make down    # docker compose down
```

For a fast loop without containers, run the API and the worker directly from
the backend environment:

```bash
cd backend
uv sync --frozen --all-groups
uv run uvicorn trendsmapp.api.app:create_app --factory --port 8000
uv run trendsmapp worker
```

## 4. Release checklist

1. `make contracts` regenerates and verifies the contract artifacts.
2. `make lint`, `make typecheck`, `make test`, and `make coverage` are green.
3. `make stubs` finds no placeholder branch.
4. The migration was applied to a copy of the production database and the
   downgrade was verified.
5. The image was scanned (`trivy`) and the bill of materials was produced.
6. `CHANGELOG.md` records the user-visible and contract-visible changes.
7. The contract change is recorded in `contracts/COMPATIBILITY.md`.
