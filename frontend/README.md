# Trendsmapp frontend

The public frontend of Trendsmapp: a Next.js App Router application that
renders the published contract and the live status of the scientific backend.
It never performs a scientific computation.

## Commands

```bash
pnpm install --frozen-lockfile   # install the exact dependency graph
pnpm run dev                     # development server on http://localhost:3000
pnpm run build                   # production build
pnpm run start                   # serve the production build
pnpm run lint                    # ESLint (flat configuration, type aware)
pnpm run typecheck               # tsc --noEmit with strict settings
pnpm run test                    # Vitest unit and component tests
pnpm run test:coverage           # Vitest with the V8 coverage report
pnpm run e2e                     # Playwright end-to-end tests
pnpm run generate:api-types      # regenerate the contract types
```

`pnpm run e2e` needs the browsers once: `pnpm exec playwright install chromium`.

## Environment

Copy `.env.example` to `.env.local` and adjust the values.

| Variable                    | Scope   | Purpose                                                                  |
| --------------------------- | ------- | ------------------------------------------------------------------------ |
| `BACKEND_API_ORIGIN`        | server  | Origin of the scientific API used for server-side rendering              |
| `NEXT_PUBLIC_API_BASE_URL`  | browser | Origin of the public API used for browser refreshes; empty disables them |
| `NEXT_PUBLIC_SITE_URL`      | browser | Public origin of this site, used for the sitemap and the canonical URL   |
| `TRENDSMAPP_API_TIMEOUT_MS` | server  | Timeout of a server-side API call                                        |

No secret is ever exposed to the browser. The server-only environment module is
import-protected: the ESLint import boundary rejects any import of
`@/lib/env/server` outside the server code.

## Structure

| Path                             | Responsibility                                                  |
| -------------------------------- | --------------------------------------------------------------- |
| `src/app/`                       | Routes, layouts, error boundaries, robots, and sitemap          |
| `src/components/`                | Presentational components and the live status panel             |
| `src/lib/api/`                   | Typed fetch client, typed errors, status reader                 |
| `src/lib/contracts/`             | Generated contract types and the hand-written runtime schemas   |
| `src/lib/env/`                   | Server-only and public environment validation                   |
| `src/providers/`                 | React Query provider                                            |
| `scripts/generate-api-types.mjs` | Regenerates the contract types from `contracts/openapi.v1.json` |
| `tests/`                         | Vitest unit and component tests                                 |
| `tests/e2e/`                     | Playwright end-to-end tests                                     |

## Contract types

`src/lib/contracts/generated.ts` is generated from `contracts/openapi.v1.json`
and must never be edited by hand. The runtime schemas in
`src/lib/contracts/runtime.ts` are written by hand and validate every response
at the network boundary. CI fails when the OpenAPI snapshot changes without a
regenerated contract file.

## Deployment

Netlify builds this directory with `pnpm run build`. The backend is a separate
container service; see `docs/deployment.md`.
