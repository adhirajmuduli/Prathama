# Trendsmapp Audit & Action Plan

Date: 2026-08-22
Scope: full-repo scan of `app.py`, `config.py`, `db.py`, `routes/*`, `utils/*`,
`static/js/*`, `templates/*`, `tests/*`, `scripts/*`, `Dockerfile`,
`docker-compose.yml`, `.github/workflows/ci.yml`, docs, and git-tracked artifacts.

Severity legend: **P0** = fix before any shared/public deployment · **P1** = fix
before release/submission · **P2** = quality/robustness debt · **P3** = hygiene.

## Progress log

- **2026-08-22 — P0 batch complete.** `/generate-heatmap` now enforces
  `max_processed_rows`/`max_timestamps` and dedupes requested timestamps;
  request bodies are capped by `BodyLimitMiddleware` (413); heatmap, upload,
  demo parsing, legend, and animation all run off the event loop via
  `asyncio.to_thread`, with heavy science jobs bounded by
  `TRENDSMAPP_MAX_CONCURRENT_JOBS` (`utils/jobs.py`) and Matplotlib rendering
  serialized by a process-wide lock; optional shared-token auth added
  (`TRENDSMAPP_AUTH_TOKEN`, `utils/security.py`) covering data/compute routes,
  router-level dependencies, and uploaded boundary files while keeping
  `/api/health` public; `SECRET_KEY` is now ephemeral-random when unset and the
  app refuses to start under `TRENDSMAPP_HTTPS_ONLY=true` without an explicit
  unique secret; compose fallback secret removed; `.env.example`, README
  configuration table, and architecture trust-boundary docs updated. Verified:
  36/36 pytest green (14 new regression tests in
  `tests/test_security_and_limits.py`), `node --check` clean, live uvicorn
  smoke tests for health/auth/fail-fast.

- **2026-08-22 — P1 batch complete.**
  (5) Disk lifecycle: `/api/demo` parses the workbook in place behind a stable
  `__demo__` session marker resolved by the animation route — zero copies;
  new uploads/boundaries replace the previous session file
  (`utils/storage.py::remove_replaced_upload`); startup TTL sweep
  (`TRENDSMAPP_UPLOAD_TTL_HOURS`, default 24) purges generated files; all 42
  orphan boundary artifacts and 65 stale uploads deleted.
  (6) Database→science bridge: shared envelope extracted to
  `utils/datasets.py`; new `POST /api/export-dataset` materializes saved DB
  measurements as a real CSV session dataset consumed by heatmap+animation;
  "Load saved table" button wired in `app.js`. *Deferred consciously:* the
  `Measurement.sampled_at` Date→DateTime migration — no Alembic present and
  `create_all` cannot migrate existing tables, so changing the type would
  silently diverge deployed schemas; the date-grain contract is documented
  until a migration tool lands.
  (7) AG Grid 29.3.3 + Bootstrap 5.3.0 vendored under `static/vendor/`
  (checksummed in `scripts/verify_assets.py`, now 7 assets); data-entry page is
  CDN-free, matching the offline claim.
  (8) `/generate-heatmap` now rejects mixed-parameter payloads or filters to an
  explicit `parameter`, echoes it in the response, and the frontend passes it.
  (9) Persistent mutations: `POST /api/table/delete-series`,
  `POST /api/table/rename-parameter`; grid context-menu delete and group rename
  hit the server then reload truth; dead `station_id` payload field removed;
  500-blank-row preload reduced to 25 template rows; timestamp-column renaming
  disabled (measurements are keyed by date).
  Verified: 50/50 pytest green (14 new tests in `tests/test_p1_lifecycle.py`),
  `node --check` + `verify_assets.py` + `verify_example.py` clean, live smoke:
  demo creates no files, export works end-to-end, data-entry page fully local.

- **2026-08-22 — P2 batch complete.**
  (10) PostgreSQL `sslmode` now maps to real TLS semantics: `verify-ca`/
  `verify-full` build an `SSLContext` validating the certificate chain against
  `sslrootcert` or system roots (`verify-full` also checks hostname),
  `require` encrypts without authentication, `disable` forces plaintext;
  unreadable CA paths fail fast.
  (11) Animation pacing is gap-proportional: deterministic largest-remainder
  allocation distributes the requested transition frames across observed
  intervals (min one frame each), so playback speed reflects real elapsed time;
  total frame budget and labels unchanged; documented in scientific-methods.md.
  (12) The map legend now renders the server's matplotlib colorbar PNG
  (new `orientation=horizontal` support on `/legend/*.png`) instead of a
  hardcoded CSS gradient approximation; dead COLOR_GRADIENTS table removed.
  (13) `_pivot_measurements` refuses to collapse duplicate station/parameter/
  date rows and reports examples instead of silently keeping the last value.
  (14) `SecurityHeadersMiddleware` attaches a self-origin CSP (blob allowances
  for MapLibre workers/surface images/MP4), nosniff, DENY framing, and strict
  Referrer-Policy to every response; data-entry page de-inlined (styles moved
  to `static/css/data-entry.css`, error handler into `data_entry.js`);
  `/api/health` no longer discloses framework/version.
  (15) Limits centralized in config: `TRENDSMAPP_MAX_VIDEO_FRAMES`,
  `TRENDSMAPP_SURFACE_RESOLUTION`, `TRENDSMAPP_ANIMATION_RESOLUTION`
  (defaults preserve 300/220/160 behavior).
  (16) CI gained pinned `ruff check` and `pip-audit` gates. Coordinated
  dependency upgrade eliminated all 33 known vulnerabilities: fastapi
  0.115.12→0.141.1, starlette 0.46.2→1.6.0, pillow 11.3.0→12.3.0,
  python-multipart 0.0.20→0.0.32, python-dotenv 1.1.1→1.2.2,
  pytest 8.3.5→9.1.1, pytest-asyncio 0.24.0→1.4.0; lock regenerated with newly
  required transitives (annotated-doc, backports.asyncio.runner, Pygments —
  previously unpinned).
  Verified: 67/67 pytest green (17 new tests in `tests/test_p2_refinements.py`),
  ruff clean, pip-audit "No known vulnerabilities found" against the new lock,
  `node --check` clean, live smoke: headers present on all responses, health
  body minimal, horizontal legend renders, pages load without inline style.

- **2026-08-22 — P3 batch complete.**
  Junk removed from version control: 0-byte `python`, root `Testfile.xlsx`,
  `uploads/Testfile.xlsx`; `.gitignore` exception dropped and `.pytest_cache`
  ignored. `oink.env` secret-loading fallback deleted from `db.py`.
  Six `console.log` debug calls stripped from `static/js/data_entry.js`.
  Benchmark now takes `--repeats` (default 3) so min/median/max are meaningful;
  verified end-to-end via a quick single-repeat smoke run.
  New `scripts/check_requirements_sync.py` gates CI against direct-pin drift
  between `requirements.txt` and the lock.
  **Bug found and fixed during cleanup:** the P1 startup sweep could delete any
  aged file in managed directories — it silently consumed the tracked
  `uploads/Testfile.xlsx`. The sweep is now scoped to application-generated
  `{uuid4().hex}_…` artifacts only, with a regression test asserting foreign
  files survive (`test_purge_expired_files_respects_ttl`).
  **Still open (author decisions, not code):** `examples/chilika_demo.xlsx`
  provenance/license documentation and the CITATION.cff repository URL remain
  submission blockers tracked in the checklist below.
  Verified: 67/67 pytest green, ruff clean, sync/asset/example verifiers pass,
  `node --check` clean on both page scripts.

- **2026-08-22 — Incident: video-generation freeze — root-caused and fixed.**
  Symptom: an MP4 request on the bundled-style Testfile.xlsx workbook (33
  stations × 12 months) burned ~221 s of full-core CPU per attempt and made
  the machine unresponsive. Diagnosis via instrumented reproduction showed
  rendering/encoding were trivial (~4.5 s combined) while
  `interpolate_surface` spent ~18.4 s *per surface* in boundary masking:
  shapely's vectorized `contains_xy` does not auto-prepare geometries, so each
  of the 25,600 grid cells ran an O(vertices) point-in-polygon test against
  the 10,089-vertex Chilika coastline. Measured directly: 18.80 s unprepared
  vs 0.0099 s prepared, bit-identical masks.
  Fix: `ensure_prepared()` applied in `load_boundary` and defensively inside
  `interpolate_surface`; `fetch_data_for_animation` converted to synchronous
  work offloaded via `asyncio.to_thread` (it had blocked the event loop);
  animation/surface trigger buttons now disable while their job runs to stop
  retry stacking.
  Result: same pipeline now completes in **4.5 s offline / 6.4 s over HTTP**
  with byte-identical MP4 output; whole test suite dropped from ~5 min to 13 s
  because its own animation tests paid the same tax. Benchmarks republished
  (`--repeats 3`): IDW-100 stations 18.170 s → 0.115 s; IDW-1,000 → 1.791 s;
  KDE-100 → 0.178 s; 91-frame MP4 62.943 s → 9.036 s. README performance and
  docs/performance.md updated with the fix note. New regression test pins
  prepared-boundary behavior and raw/prepared equivalence
  (`test_boundaries_are_prepared_for_fast_masking`). 68/68 tests green.

- **2026-08-22 — Guided first-run tour added.**
  New `static/js/tour.js` + `static/css/tour.css` (dependency-free, CSP-clean,
  vendored-policy compliant): 11-step walkthrough with spotlight highlighting,
  Next/Back/Skip controls, step counter, close button, Escape/arrow-key
  navigation, viewport-clamped card placement with reflow on scroll/resize,
  and reduced-motion support. Content covers upload formats (long/wide
  examples embedded), example/database loading, boundary GeoJSON requirements
  (external guide link slot — `GEOJSON_GUIDE_URL` constant in tour.js, empty =
  honest placeholder until a URL is chosen), method selection with IDW power /
  KDE bandwidth significance, surface generation and the matplotlib colorbar
  legend, animation pipeline semantics, spreadsheet table editing, and
  capture/export. Auto-starts once per browser via localStorage; "Take a tour"
  button in the sidebar header restarts it. CI gained
  `node --check static/js/tour.js`; README capabilities and verification lists
  updated. Verified: syntax checks pass, live server serves page hooks and
  both assets (200), 68/68 pytest green.

- **2026-08-22 — Data-entry grid refactor.**
  Dates are now first-class: every timestamp column header carries a native
  calendar picker and displays dd/mm/yyyy; picking a new date calls the new
  `POST /api/table/rename-timestamp` endpoint (per-parameter or all-parameter
  move, 409 on conflicting station/parameter/date, `allow_missing` for unsaved
  template columns with local relabel fallback). The grid opens as a
  100x100 canvas (100 blank rows plus date columns padded to 100 under a
  clearly-labelled scratch group) extendable via the add buttons. All add
  buttons are popup-free: "+ Timestamp" appends a next-date column to every
  parameter group, "+ Parameter" creates an auto-named group with today's
  date, "+ Coordinate" appends a blank row. Deletion is embedded in headers:
  a red "−" in each date header deletes that series server-side (local removal
  for never-saved columns), and a pinned row-index column gives each coordinate
  row its own "−" to remove it from the grid. Verified: 72/72 pytest green
  (5 new rename-timestamp tests), ruff clean, node --check clean on all three
  page scripts, live smoke confirms page serving, rename flow, and pivot key
  movement.

- **2026-08-22 — Grid header components fixed + fully in-sheet editing.**
  Root causes for missing calendar/delete controls: (a) custom components were
  attached via inline `headerComponentFramework`/`cellRendererFramework`
  classes, which are unreliable in the vanilla UMD AG Grid bundle — all three
  components now register through `gridOptions.components` and are referenced
  by string name (`headerComponent`, `headerGroupComponent`, `cellRenderer`);
  (b) the script cache-buster was still at v2.2.0, so browsers served the
  pre-refactor file — bumped to v3.0.0. The calendar now shows a real SVG icon
  wrapping an invisible native date input (click opens the picker everywhere;
  `showPicker()` used where available). Parameter group headers became custom
  in-sheet components: double-click renames inline (Enter commits, Escape
  cancels; saved parameters go through rename-parameter, unsaved ones relabel
  locally) and each carries its own "−" that deletes the whole parameter.
  The Bootstrap prompt modal was removed entirely — every add/rename/delete
  now happens in the sheet. Verified: node --check clean, 35 targeted pytest
  green, live smoke confirms modal removal and new bundle serving.

- **2026-08-22 — Grid console-error cleanup (user-reported CSP + AG Grid logs).**
  Removed the last inline style attribute (`<html style="height:100%">` →
  covered by data-entry.css), satisfying `style-src-attr`. Added `data:` to
  `font-src` so AG Grid's embedded base64 theme fonts load under the strict
  CSP. Dropped Enterprise-only grid options (`enableRangeSelection`,
  `getContextMenuItems`) and the invalid `enableClipboard` property — the
  community clipboard paste pipeline (processDataFromClipboard) remains.
  Hardened both custom header components against `params.colDef` being
  undefined, fixing the reported `can't access property "isoDate"` crash.
  Cache-buster bumped to v3.1.0. Verified: node --check clean, 17 security/CSP
  tests pass, live smoke shows `font-src 'self' data:` in the served policy and
  no inline style attribute on the page.

---

## Executive summary

| # | Finding | Where | Severity |
|---|---|---|---|
| 1 | `/generate-heatmap` bypasses row/timestamp limits (CPU/memory DoS) | `app.py:245-302` | **P0** |
| 2 | CPU-bound work runs synchronously on the event loop (single worker freezes) | `app.py:245-337`, upload path | **P0** |
| 3 | No authentication or authorization anywhere (anonymous DB writes/deletes) | `routes/data_api.py` | **P0** |
| 4 | Hardcoded default `SECRET_KEY` + compose fallback secret | `config.py:49`, `docker-compose.yml` | **P0** |
| 5 | Uploads/boundaries accumulate forever; demo copies file on *every page load* | `app.py:201-215`, `uploads/`, `static/data/uploads/` | **P1** |
| 6 | Two disconnected data planes: DB (data-entry) can never be visualized/animated | `db.py`, `routes/data_api.py`, `utils/animation_generator.py` | **P1** |
| 7 | CDN scripts (AG Grid, Bootstrap) without SRI; contradicts "no CDN" claim | `templates/data-entry.html:114-115` | **P1** |
| 8 | `/generate-heatmap` mixes parameters (colocated different-analyte averaging) | `app.py:268-284`, `utils/spatial_rendering.py:76-77` | **P1** |
| 9 | Client-side-only delete/rename in data-entry → silent data resurrection/duplication | `static/js/data_entry.js:438-580` | **P1** |
| 10 | `sslmode=verify-ca/verify-full` silently degraded to plain TLS | `db.py:36-39` | **P2** |
| 11 | Animation blends ignore real time gaps (uniform alpha per transition) | `utils/animation_generator.py:93-105` | **P2** |
| 12 | Server `/legend/*.png` endpoint is dead code; CSS gradient approximation used instead | `app.py:323`, `static/js/app.js:9-14,291` | **P2** |
| 13 | `sampled_at` stored as `Date` (time truncated) vs full UTC pipeline timestamps | `db.py:78` vs `utils/data_processing.py:59` | **P2** |
| 14 | Tracked junk: 0-byte `python`, `Testfile.xlsx` (root + uploads/) | repo root | **P3** |
| 15 | `oink.env` secret-loading fallback (undocumented leftover) | `db.py:17-20` | **P3** |

---

## P0 — Critical (security & availability)

### 1. `/generate-heatmap` bypasses documented limits
- Client posts arbitrary JSON `data` + `timestamp_columns`. The handler checks
  only the 500-stations-per-frame cap inside the loop. It never enforces
  `max_processed_rows` (100k) or `max_timestamps` (100) — unlike `/upload`
  (`app.py:117-141`).
- Attack: one request with e.g. 10,000 timestamps × ≤500 stations triggers
  10,000 × 220×220 IDW/KDE grids + base64 PNGs in memory → OOM/CPU exhaustion.
- **Fix:** validate `len(observations) <= settings.max_processed_rows` and
  `len(timestamps) <= settings.max_timestamps` immediately after normalization,
  before any interpolation; reject over-limit payloads with 400.

### 2. Blocking CPU work inside async handlers
- `/generate-heatmap` runs interpolation + Matplotlib rendering inline in the
  coroutine (`app.py:266-286`). With `uvicorn --workers 1` (Dockerfile CMD),
  one 18-second surface stalls *all* requests including `/api/health` → Docker
  healthcheck kills the container under normal scientific load.
- Also blocking: `_dataset_payload` (pandas parse) in `/upload` and `/api/demo`;
  legend figure rendering.
- **Fix:** wrap CPU sections in `await asyncio.to_thread(...)` exactly as
  `/api/animate` already does (`routes/animation_api.py:66-76`); consider
  `run_in_threadpool` from Starlette. Add a bounded semaphore to serialize
  heavy jobs.

### 3. Zero authentication / authorization
- Anonymous users can create/update/delete database measurements
  (`POST /api/table`, `DELETE /api/measurement`), upload arbitrary files, and
  trigger expensive computation. Any public URL equals open write access.
- **Fix (prototype-appropriate):** add a dependency-injected guard (static
  bearer token or HTTP basic via env var, disabled only for localhost dev);
  protect all mutating + compute endpoints. Document the trust model in
  `docs/architecture.md`. Longer term: real user accounts if multi-user.

### 4. Secret key handling
- `config.py:49` falls back to a committed constant; `docker-compose.yml` ships
  another known default. Sessions are itsdangerous-signed cookies; with a known
  key an attacker can forge `uploaded_filename`/`boundary_geojson` and hijack
  other users' uploaded datasets into their own animation jobs.
- **Fix:** refuse to start (or log loud warnings + disable session endpoints)
  when `SECRET_KEY` equals a known default and the deployment is not
  localhost; generate a random key at first boot persisted to the data volume;
  update compose example to require `${SECRET_KEY}` with no default.

---

## P1 — High

### 5. Unbounded disk growth, no lifecycle for uploads
- Every `/api/demo` hit copies the workbook to `uploads/<uuid>_…` and it is
  never deleted — and `index.html` auto-calls `/api/demo` on every page load
  when demo mode is on (`static/js/app.js:462`). Boundary uploads pile up
  (26 orphaned test files currently sit in `static/data/uploads/`). No GC
  anywhere.
- **Fix:** (a) serve the demo without copying (parse directly from
  `examples/`, keep filename stable in session); (b) TTL sweeper or
  delete-on-new-upload-per-session; (c) cap directory size; (d) clean the
  existing orphans and stop shipping them.

### 6. Database plane is disconnected from science plane (broken E2E flow)
- Data-entry writes `stations/parameters/measurements` tables, but nothing ever
  reads them for mapping: `/generate-heatmap` consumes client-posted JSON;
  `/api/animate` re-reads the session's uploaded *file* only
  (`fetch_data_for_animation`). Saving the grid redirects to `/`, which just
  reloads the demo. User-entered data can never be mapped or animated.
- **Fix:** add `GET /api/export-dataset` (or `POST /dataset/from-db`) that
  pivots DB measurements into the same normalized payload shape used by
  `/upload`, stores it as a session dataset (in-memory cache or generated
  temp file), and returns the same envelope (`data/stats/filename/…`) so
  `app.js` can treat it identically.
- Related schema gap: `Measurement.sampled_at` is `Date`-only (`db.py:78`)
  while the pipeline canonicalizes `…T00:00:00Z` strings — time-of-day is
  destroyed and the two planes would disagree. Migrate to `DateTime(timezone=True)`.

### 7. Data-entry page violates the vendored/offline asset policy
- `templates/data-entry.html` pulls AG Grid 29.3.3 and Bootstrap 5.3.0 from
  jsdelivr with **no `integrity`/`crossorigin` attributes**, contradicting the
  README claim that browser assets are local ("no token or CDN connection").
- **Fix:** vendor both libraries under `static/vendor/` with SHA-256 checksums
  added to `scripts/verify_assets.py` (mirroring the MapLibre pattern), or at
  minimum pin + add SRI hashes.

### 8. Parameter-blind heatmaps (scientific correctness)
- `/generate-heatmap` accepts mixed-parameter observation arrays. Colocated
  stations of *different analytes* are mean-aggregated together in
  `interpolate_surface` (`np.unique` + mean), producing physically meaningless
  surfaces. The web UI filters client-side so the bug hides; direct API users
  get wrong science silently.
- **Fix:** require a `parameter` field; reject (400) payloads containing more
  than one distinct parameter; echo the parameter in the response and method
  headers.

### 9. Data-entry mutations that don't persist / corrupt
- `deleteColumnOrGroup` (`data_entry.js:561`) removes only client column defs:
  deleted series reappear after reload; `DELETE /api/measurement` is never
  called from the UI.
- Renaming a parameter header (`handleHeaderDoubleClick`) renames locally;
  saving inserts *new* parameter rows while old ones remain → duplicates.
- Save sends a `station_id` field the backend ignores (`data_entry.js:230`);
  500 blank rows preloaded into the grid (`data_entry.js:104`).
- **Fix:** implement server endpoints for series delete and parameter rename
  (transactional), wire context-menu actions to them; drop `station_id` or
  honor it; render only real rows + one blank entry row.

---

## P2 — Medium

### 10. TLS verification downgrade (Postgres)
`sslmode=require|verify-ca|verify-full` all collapse to `ssl=True`
(`db.py:36-39`); asyncpg then skips certificate/hostname verification.
Map verify modes to `ssl.SSLContext` with `check_hostname=True` /
`load_verify_locations(cafile)`; treat `require` as encryption-only explicitly.

### 11. Animation temporal distortion
Blend alpha is `step/frames_per_transition` regardless of the actual interval
between observed dates (`animation_generator.py:96-99`), so 1-day and 1-year
gaps animate identically — visually misleading trends. Either weight alpha by
real elapsed time (per-transition duration ∝ gap, capped) or document the
uniform-motion assumption in `docs/scientific-methods.md`.

### 12. Legend mismatch / dead endpoint
`GET /legend/{timestamp}.png` has zero frontend callers; the UI paints an
approximate CSS gradient from 5 hardcoded hex stops per colormap
(`app.js:9-14`), which will not match matplotlib's actual colormap rendering.
Either delete the route or use it (an `<img>` legend) for exact fidelity.

### 13. Silent collapse in `/api/table`
`pivot_table(aggfunc="last")` (`routes/data_api.py:86-88`) hides duplicate
station/parameter/date conflicts by keeping the last value. Detect duplicates
and either 409 or expose a conflict list instead of silently dropping history.

### 14. Missing hardening headers & misc web hygiene
No CSP / `X-Content-Type-Options: nosniff` / `X-Frame-Options` /
Referrer-Policy on HTML responses. `/api/health` discloses version. Add a small
middleware for headers; keep version out of public health payload (or accept
and document).

### 15. Hardcoded/non-centralized limits
`MAX_VIDEO_FRAMES = 300` (`animation_generator.py:16`), animation resolution
160 vs interactive 220 (`app.py` default vs `animation_generator.py:84`) are
magic numbers outside `config.py`; causes MP4/map visual inconsistency and
prevents ops tuning. Move into `Settings` (`max_video_frames`,
`animation_resolution`, `surface_resolution`).

### 16. Test coverage gaps
Nothing covers: `/generate-heatmap` limit enforcement (#1), event-loop
blocking (#2), parameter mixing (#8), legend endpoint, `/api/table` duplicate
collapse (#13), concurrent animation load, or DB→visualization export once
added (#6). Add regression tests alongside each fix; add `ruff` +
`eslint`/`node --check` (already present) + `pip-audit` to CI.

---

## P3 — Hygiene

- Remove tracked junk: 0-byte `python` file, `Testfile.xlsx` at repo root,
  `uploads/Testfile.xlsx` (also referenced oddly in `.gitignore`
  `!uploads/Testfile.xlsx`).
- Delete the `oink.env` loading fallback in `db.py:17-20` (undocumented
  personal convention; secret-leak hazard). Rely on `.env` only.
- `requirements.txt` vs `requirements.lock.txt` duplication: define lock as the
  single source (CI installs lock ✔) and add a CI check that the two agree, or
  reduce `requirements.txt` to abstract names.
- Strip `console.log` debug calls from `static/js/data_entry.js`; remove dead
  `#myGrid` CSS in `templates/data-entry.html`.
- `benchmarks/latest.json` regeneration workflow: `timed(repeats=1)` makes
  min/median/max identical; raise default repeats.
- `examples/chilika_demo.xlsx` provenance still unresolved (own admission in
  `examples/README.md`) — block journal submission on this.

---

## Explicitly verified as OK (no action)

- Path-traversal guards on boundary paths (`app.py:104-114`,
  `routes/animation_api.py:32-38`): resolve + allowlist-parents checks are
  sound.
- Upload streaming with byte cap + unlink-on-failure (`app.py:86-101`).
- Strict normalization: alias handling rejects positional guessing; blank-wide
  vs malformed-value semantics; UTC canonicalization
  (`utils/data_processing.py`).
- IDW exact-hit → colocated mean; KDE underflow → nearest aggregate; both
  documented in `docs/scientific-methods.md`.
- Boundary repair via buffer(0), single-feature Polygon/MultiPolygon rule.
- Animation correctly offloaded via `asyncio.to_thread`; MP4 signature &
  size sanity check; session binding of filenames works as designed (modulo #4).
- Transactional session wrapper with rollback (`db.py:85-95`).
- Container runs non-root UID 10001, tmpfs, no-new-privileges, healthcheck.
- CI runs tests, checksum verifications, JS syntax checks, container build +
  smoke.

---

## Suggested execution order

1. **P0 batch (1 day):** limits in `/generate-heatmap`; `to_thread` +
   semaphore for heatmap/upload/legend; SECRET_KEY startup guard; minimal
   auth dependency on mutating endpoints.
2. **P1 batch (2–4 days):** upload/boundary GC + demo-no-copy; vendored AG
   Grid/Bootstrap + checksums; DB→session-dataset export endpoint (closes the
   broken E2E flow); server-side parameter filter for heatmaps; data-entry
   delete/rename persistence.
3. **P2/P3 sweep:** SSL verify modes, time-proportional animation option,
   legend decision, header middleware, config centralization, tests, repo
   cleanup, doc updates (`architecture.md` trust boundaries, README claims).
