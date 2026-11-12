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
| `NEXT_PUBLIC_TURNSTILE_SITE_KEY` | Public Cloudflare Turnstile site key for the contact form |

No secret belongs in the frontend. The server-only environment module is
protected by an ESLint import boundary, so a secret cannot be read by browser
code by accident.

#### Contact form (server-side only; all optional — the route answers 503 when absent)

| Variable | Purpose |
| --- | --- |
| `TURNSTILE_SECRET_KEY` | Cloudflare Turnstile secret for the mandatory server-side siteverify |
| `UPSTASH_REST_URL`, `UPSTASH_REST_TOKEN` | Upstash Redis REST credentials for rate limiting and idempotency |
| `RESEND_API_KEY` | Resend API key for transactional delivery |
| `CONTACT_FROM_EMAIL`, `CONTACT_TO_EMAIL` | Sender and recipient of contact messages |
| `CONTACT_HASH_SECRET` | HMAC secret for hashing IP/email; defaults to the Turnstile secret |
| `CONTACT_RATE_LIMIT_WINDOW_MS`, `CONTACT_RATE_LIMIT_IP_PER_WINDOW`, `CONTACT_RATE_LIMIT_EMAIL_PER_WINDOW` | Sliding-window limits (defaults 1 h, 5 per IP, 3 per email) |
| `CONTACT_IDEMPOTENCY_TTL_SECONDS` | Duplicate-suppression TTL (default 24 h) |

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

For a fast loop without containers, run the API and the worker in one process
(the command applies the database migrations first, then serves and polls):

```bash
cd backend
uv sync --frozen --all-groups
uv run trendsmapp dev --port 8000
```

Or run them separately, as production does:

```bash
uv run uvicorn trendsmapp.api.app:create_app --factory --port 8000
uv run trendsmapp worker
```

## 4. Troubleshooting "deployed but the page does not render"

Work top-down; most blank-page reports are one of the first three items.

1. **Is the Next.js runtime actually serving the deploy?** A deploy can be
   "successful" while publishing raw build output. Check, in order:
   - The deploy log line `Custom publish path detected. Proceeding with the
     specified path: 'frontend'` is the tell: the site's **UI publish
     directory is set to `frontend`**, which overrides the Next.js adapter and
     serves raw source → 404 on every route. Fix in the Netlify UI: **Site
     settings → Build & deploy → Publish directory → clear it (leave empty)**.
     Do not set `publish` in `netlify.toml` either; the adapter owns it.
     (`publishOrigin: ui` in a deploy log's resolved config shows the same.)
   - `@netlify/nextjs` is auto-provisioned by Netlify when absent from
     `package.json`. If you pin it there, you MUST also regenerate
     `frontend/pnpm-lock.yaml` (`pnpm install` on a networked machine, commit
     it) — Netlify and CI install with frozen-lockfile and otherwise fail with
     `ERR_PNPM_OUTDATED_LOCKFILE`.
   - The Netlify **deploy log** contains the adapter run lines and the route
     table (`ƒ /`, `ƒ /api/contact`, …), not just `next build`.
   - `curl -sI https://<site>/` shows an `x-nf-request-id` header (served by
     the Next runtime) rather than a plain static response.
   - The Netlify **Functions** tab lists the Next handler functions.
2. **Do the page chunks load?** In the browser Network tab, every
   `/_next/static/*.js` referenced by the HTML must return 200. A 404 there
   means the publish directory is wrong (item 1) — the SSR HTML may still
   show, but hydration never runs and the page looks dead on interaction.
3. **Is an environment variable present but blank?** Deployment UIs often
   keep a variable set to `""` to mean "unset". Blank values are normalized
   to unset by `src/lib/env/read-env.ts`; before that fix, a blank
   `NEXT_PUBLIC_SITE_URL` or `BACKEND_API_ORIGIN` failed schema validation at
   module load and errored every page. Check the site's environment variable
   list for blank values and clear them.
4. **Check the function logs** (Netlify → Functions → logs) for the request
   identifier shown by `app/error.tsx`, and the browser **console** for
   hydration errors. The reported Firefox "Source map error: URL constructor:
   is not a valid URL" with `Resource URL: about:srcdoc` and an empty Source
   Map URL comes from devtools' own source-map worker and is noise — ignore
   it; it is not a page failure.
5. **Verify the backend origin** used at request time: the home page calls
   `BACKEND_API_ORIGIN` server-side on every request (`dynamic =
   "force-dynamic"`); failures are caught and shown as a status banner, not a
   blank page, but a wrong origin still means no live data.

## 5. Release checklist

1. `make contracts` regenerates and verifies the contract artifacts.
2. `make lint`, `make typecheck`, `make test`, and `make coverage` are green.
3. `make stubs` finds no placeholder branch.
4. The migration was applied to a copy of the production database and the
   downgrade was verified.
5. The image was scanned (`trivy`) and the bill of materials was produced.
6. `CHANGELOG.md` records the user-visible and contract-visible changes.
7. The contract change is recorded in `contracts/COMPATIBILITY.md`.
