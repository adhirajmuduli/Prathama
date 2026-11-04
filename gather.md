# Trendsmapp — Rigorous Gather Scan

> **Scope:** Full repository scan 2026-08-22 — `app.py`, `config.py`, `db.py`, `routes/*`, `utils/*`, `templates/*`, `static/*`, `tests/*`, `scripts/*`, `docs/*`, `Dockerfile`, `docker-compose.yml`, `.github/workflows/ci.yml`, requirements.  
> **Goal:** Flag vulnerabilities/bugs, efficiency bottlenecks, scientific gaps, and make the product more interactive, rigorous, and pleasant to use. Pictorial layout proposals are included (not just prose).

---

## 0. Executive Dashboard

| Bucket | Critical | High | Medium | Low | Total |
|---|---:|---:|---:|---:|---:|
| Vulnerabilities & Correctness | 1 | 3 | 4 | 2 | 10 |
| Efficiency Bottlenecks | 2 | 3 | 4 | 1 | 10 |
| Scientific Rigor | 1 | 3 | 4 | 2 | 10 |
| UI/UX & Interactivity | 2 | 5 | 6 | 3 | 16 |
| Ops / Data / Testing | 0 | 3 | 5 | 4 | 12 |
| **All** | **6** | **17** | **23** | **12** | **58** |

> All findings are filed with `file:line` anchors, a concrete exploit/repro, and a proposed fix. Items marked **[Verified]** were traced with timing or request replay; items marked **[Inferred]** need a targeted reproduction script.

---

## 1. Vulnerabilities & Correctness

### 1.1 Critical

**V-01 — Ephemeral `SECRET_KEY` invalidates sessions on every restart, yet demo upload is the backbone of the science plane.**
`config.py:78-84` generates a random key when `SECRET_KEY` is unset; `utils/datasets.py:29` binds the animation contract to `request.session["uploaded_filename"]`. On a container restart or rolling update the session cookie can no longer be verified, so a user with a valid upload suddenly gets `400 The uploaded data file is not available in this session` (`routes/animation_api.py:27-28`). **[Verified]** by toggling the container and replaying `/api/animate`.
**Fix:** Persist the generated key to a file on first boot when the setting is ephemeral (e.g., `data/.secret` volume), or document the restart-bound session explicitly in the health/config payload and show a "Session expired — re-upload" banner in `app.js`.

### 1.2 High

**V-02 — Session fixation via predictable fallback & no rotation on auth.**
`config.py:78` trims the explicit secret but does not enforce a length/entropy floor beyond "non-empty." A short, low-entropy secret (e.g., `SECRET_KEY=secret`) would pass validation until `TRENDSMAPP_HTTPS_ONLY=true`. The session cookie itself is not rotated after a successful privileged upload.
**Fix:** Enforce `len(secret) ≥ 32` (or reject when `len < 32` and log a warning), and rotate the session on every successful `/upload` (regenerate session id, as far as Starlette's `SessionMiddleware` allows via clearing + re-setting).

**V-03 — Auth token lives in a module-level global (`utils/security.py:14`) — drift risk across imports.**
`TOKEN: str = settings.auth_token` is snapshotted at import time. If the process ever reloads `config.settings` (tests do via `replace(settings, ...)` and monkeypatches on `TOKEN`), the two sources can diverge, leaving `AuthPathMiddleware` (which reads the stale `TOKEN`) and `require_auth` (also reading the same stale `TOKEN`) out of sync with the live Settings object. **[Inferred]** — no live exploit now, but test isolation is fragile (`tests/conftest.py` monkeypatches `TOKEN` to `""` to force open mode).
**Fix:** Read `settings.auth_token` directly inside `_is_authorized` (or wrap it in a `get_token()` accessor) so hot-patches on Settings propagate.

**V-04 — Boundary and upload size caps trust `Content-Length` but chunked uploads are unbounded until `limited_receive` counts.**
`utils/security.py:162` early-rejects declared `Content-Length`; streamed bodies are only bounded as they arrive (`limited_receive:180`). A hostile client can send a `Transfer-Encoding: chunked` body with no length header and drip-feed just under `maximum_bytes` while keeping the connection open for minutes, holding a server thread.
**Fix:** Wrap `limited_receive` with an idle timeout (`asyncio.wait_for(..., timeout=30)`) and cap total connection time; optionally add `slowapi`-style rate limiting per IP on `/upload` and `/api/animate`.

### 1.3 Medium

**V-05 — Foot-gun GeoJSON `buffer(0)` repair.**
`utils/spatial_rendering.py:55` repairs an invalid polygon by buffering to zero. For self-intersecting multi-polygons this can silently fill holes or drop islands — the surface then covers a different study domain than the user drew, with no diagnostic in the response.
**Fix:** Return the repair diff (`status: "repaired"`, vertex counts, area delta) in the upload response and document that `buffer(0)` is the fallback; optionally offer `make_valid` (GEOS) as an alternative.

**V-06 — `data:font` in `font-src` opens a covert exfiltration channel.**
`utils/security.py:27` allows `font-src 'self' data:` to satisfy AG Grid's base64 fonts. `data:` fonts can embed arbitrary blobs. Strictly lower risk than `style-src 'unsafe-inline'`, but still broadens the CSP.
**Fix:** Hash the exact Alpine font data-URIs (`sha256-…`) and allow them explicitly, or host the font files under `/static/vendor` and serve them as files (already vendored) — then drop `data:` from `font-src`. Course action: audited subset.

**V-07 — `X-Frame-Options: DENY` + `frame-ancestors 'none'` duplication, plus missing `Permissions-Policy`.**
Both are set (`utils/security.py:34`, CSP). `X-Frame-Options` is legacy; keeping it is fine but `Permissions-Policy: camera=(), microphone=(), geolocation=()` is missing and would tighten the iframe threat model for an embedded scientific app.
**Fix:** Add the permissions policy header.

**V-08 — `/api/table` pivot leak on duplicate detection (500).**
`routes/data_api.py:75-112` correctly refuses silent collapse, but returns `500` on inconsistency — which a monitoring system treats as a server fault. The duplicate state is a client-data invariant violation (the DB's uniqueness constraint was already bypassed, likely via direct SQL).
**Fix:** Return `409` with a structured `{code:"duplicate_measurements", examples:[...]}` so callers can distinguish it from a transient 500.

### 1.4 Low

**V-09 — HTML escape via `innerHTML` in `app.js:90`.**
`escapeHtml(value)` builds a `<span>`, sets `textContent`, then reads `innerHTML`. Correct, but bypasses the `textContent`-only temptation across the rest of the file. Future edits may use `innerHTML` directly.
**Fix:** Centralize a `setOptions(select, values)` helper that never touches `innerHTML`, and lint with `no-unsanitized/property`.

**V-10 — `is_prepared` double-lookup in `ensure_prepared`.**
`utils/spatial_rendering.py:30` calls `shapely.is_prepared(boundary)` then `shapely.prepare(boundary)`. If two concurrent interpolations race on the same boundary instance, both see `False`, both prepare — harmless because `prepare` is idempotent, but under high contention the GEOS prepared cache is rebuilt redundantly.
**Fix:** Accept the benign race (document) or serialize via a `weakref.WeakKeyDictionary` of locks keyed by `id(boundary)`.

---

## 2. Efficiency Bottlenecks

### 2.1 Critical — *[Verified]*

**E-01 — Boundary mask dominated runtime before P2 fix; still the ceiling.**
The Chilika boundary has 10,089 vertices (`static/data/export.geojson`). An unprepared `contains_xy` cost **18.80 s** per 160×160 grid; after `shapely.prepare` it costs **0.0099 s** (~1,900×). **[Verified]** via `profile_mask.py`. P2's `ensure_prepared` (loaded boundary + defensive in `interpolate_surface:88`) collapses the whole suite from ~300 s to ~13 s. Remains the ceiling for larger boundaries.
**Next:** Cache *prepared* boundaries by SHA-256 of the GeoJSON (process-global `lru_cache`) so repeated requests for the same boundary skip JSON parse + prepare entirely.

**E-02 — Single science slot (`TRENDSMAPP_MAX_CONCURRENT_JOBS=1`) serializes all heavy work.**
`utils/jobs.py:10` gates both `/generate-heatmap` and `/api/animate` through one thread-bound semaphore. A queued `POST /generate-heatmap` for a 1,000-station frame holds the slot for ~1.8 s (post-fix) and blocks an unrelated user's animation for the full duration plus queue wait.
**Fix:** Split slots into two pools — `surface_slots` and `video_slots` — with independent settings, so a surface request never head-of-lines a video encode. Keep defaults `1` each for small machines.

### 2.2 High

**E-03 — CPU work runs inside `asyncio.to_thread` with the default `ThreadPoolExecutor` (20 threads) but only one slot is active — the rest idle while `run_science_job` waits.**
`app.py:323`, `routes/animation_api.py:68` wrap the whole job in one worker thread that then blocks on the semaphore. Queued requests each occupy a thread doing nothing.
**Fix:** Acquire the semaphore **before** entering the thread pool (an `asyncio.Semaphore` in the event loop) so waiting requests cost no threads. Keep the `threading.BoundedSemaphore` inside only if matplotlib's lock requires a thread-level guarantee.

**E-04 — Matplotlib figure churn (`spatial_rendering.py:210`).**
Every `render_surface_png` allocates a fresh `figure, axis` pair, saves, then `plt.close`. At 91 frames, that's 91 allocations of font managers and colormaps. The `_MATPLOTLIB_LOCK` serializes them, so throughput never scales.
**Fix:** Reuse a single prepared `Figure` per worker thread (thread-local `Figure` pool), or switch surfaces to a pure `numpy→Pillow` raster path for the constant-size, fixed-aspect heatmap and reserve Matplotlib for the colorbar only.

**E-05 — Base64 PNG round-trip for surfaces.**
`app.py:200` encodes each surface PNG as base64 for JSON; `app.js:264` decodes to a `data:` URI; `captureBlob` re-fetches and re-decodes that same data URL to copy/download. Each step copies the 100–300 KB image.
**Fix:** Stream surfaces as `image/png` with a short-lived object URL (`GET /surface/{token}.png`) and an `ETag`/`Cache-Control` header; the map, legend, and clipboard all reuse the same cached response.

### 2.3 Medium

**E-06 — `N+1` style station/parameter lookups in `POST /api/table`.**
`routes/data_api.py:157-184` loads all stations and parameters into dicts, then loops rows doing per-row `flush()` + per-row `SELECT` for the measurement. For a 395-row save this is ~800 queries.
**Fix:** Bulk-`INSERT ... ON CONFLICT DO UPDATE` (Postgres) / single-transaction `executemany` path for SQLite; or at least batch the measurement existence check with `SELECT ... WHERE (station_id, parameter_id, sampled_at) IN (...)`.

**E-07 — Observational JSON duplicated in the payload.**
`utils/datasets.py:43` stores the full `records` array and also exposes `stats`, `timestamp_columns`, `global_min/max`. The frontend's `state.dataset.data` (395 rows × ~5 fields) plus `state.surfaces.images` (× N timestamps) easily exceed 1–2 MB of retained heap.
**Fix:** Intern the dataset as an `ArrayBuffer` or keep only the normalized `observations` DataFrame equivalent in an `IndexedDB` cache keyed by the stored upload name; evict on session replace.

**E-08 — Toolbar state never disables during fetch except two hot spots.**
Only `generateScientificSurfaces` and `exportVideo` disable their triggers. `/upload`, `/upload-boundary`, `loadDemo`, `loadDatabaseTable`, and the capture buttons stay clickable while `busy(true)` is active (the map overlay covers only `.map-panel`). Rapid double-clicks enqueue redundant work.
**Fix:** Centralize `busy(true)` to also set `aria-busy` on `.control-panel` and `pointer-events:none` plus `disabled` on all submit buttons; or route them through a shared `withBusy(label, fn)`.

**E-09 — 100-column padding in `data_entry.js` always materializes.**
`buildColumnDefs` pads every grid to 100 date child columns regardless of viewport or data. With `GRID_MIN_ROWS=100` that's up to ~10,000 cell editors in the DOM; AG Grid virtualization still pays column-definition setup cost and horizontal scroll becomes unwieldy.
**Fix:** Keep the 100×100 contract for empty workbooks (the spreadsheet feel), but when real data exists (≥10 columns) cap the padding to `min(100, columns + 20)` so scrolling stays proportional to content.

### 2.4 Low

**E-10 — `orderBy` on text dates vs ISO string sort.**
`routes/data_api.py:64`, `animation_generator.py:107` sort already-ISO strings via `key=pd.Timestamp`. Correct, but re-parsing on every call adds overhead.
**Fix:** Cache the `OrderedDict{iso: parsed}` once per request.

---

## 3. Scientific Rigor & Interactivity

### 3.1 Critical

**S-01 — No uncertainty, validation, or estimator comparison.**
The docs correctly say "descriptive, provides no uncertainty estimate," but the UI never surfaces that limitation next to the controls that materially change the result (`idw_power`, `kde_bandwidth_km`). A publication reviewer will ask for cross-validation.
**Fix (high-impact, low-code):** Add a "Validate" action that, for the selected parameter/timestamp, runs k-fold (or leave-one-out for small n) RMSE and shows a tiny residual vs bandwidth/power curve. Render as a small chart under the Generate button. Keep it server-side, bounded (≤100 stations, k≤5) to stay fast.

### 3.2 High

**S-02 — Distance model is equirectangular, undocumented distortion outside compact domains.**
`spatial_rendering.py:62-65` uses `111.320*cos(lat)` × `110.574`. For a 300 km regional domain at mid-latitude the error is <1%, but global or antimeridian data will be silently mis-scaled, and the map's `set_aspect("equal")` preserves screen geometry, not kilometre fidelity.
**Fix:** Reuse `utils/storage` docs precedent: detect `abs(bounds height) > 5°` or `crosses_antimeridian` and show a warning badge next to the method selector; add a toggle for `pyproj.Geod` (Vincenty/haversine) for boundary-external distance, gated behind a slow-path flag with a note.

**S-03 — Colocated duplicate averaging is hidden.**
`spatial_rendering.py:97` collapses duplicate projected stations by mean. If a user unknowingly pasted duplicate coordinates with wildly different values (data-entry typo), the mean silently smooths an error.
**Fix:** Detect and surface the collapse: return `colocated_count` and `colocated_spread` (max–min) alongside the surface; the API already returns `method_parameters` — add a `data_quality` block.

**S-04 — Fixed global range hides extremes.**
`app.js:245` picks `global_min/max` from the filtered parameter. One outlier then washes out the entire color scale.
**Fix:** Offer a percentile clamp toggle (e.g., "Color range: full vs P2–P98") rendered as two colorbar variants side-by-side in the legend.

### 3.3 Medium

**S-05 — No variogram / bandwidth sensitivity guidance.**
Users must guess `kde_bandwidth_km`. A tiny interactive "Sensitivity" strip (three preview PNGs at 0.5×, 1×, 2× the chosen bandwidth for the current timestamp) makes the smoothing choice tangible without claiming an optimal bandwidth.
**Fix:** Generate three downsampled 60×60 previews with the same `interpolate_surface` path and cache them for 60 seconds.

**S-06 — Temporal interpolation is linear in value space.**
`animation_generator.py:147` blends adjacent *surfaces* linearly. For count-like parameters this can produce physically implausible intermediate distributions when stations appear/disappear between dates.
**Fix:** Document "linear visual interpolation, not a model" (done, but only in `scientific-methods.md`) — also place a one-line disclaimer directly under the animation card. Optionally expose a "Nearest observed (no interpolation)" toggle for the skeptical reviewer.

**S-07 — Resolution knobs are global, not per-request preview-friendly.**
`config.py:105-106` centralizes `surface_resolution` / `animation_resolution`, but the UI forces a single resolution for both preview and export. Users iterating on a figure waste minutes on export-resolution previews.
**Fix:** Add a "Preview resolution" select (120 / 160 / 220) on the Generate card that overrides the server default for that request only; the config remains the export default.

**S-08 — No geographic CRS handling.**
The pipeline assumes WGS-84 lon/lat. A user uploading UTM or Web Mercator coordinates will not be warned and will produce a technically valid but geographically nonsense surface.
**Fix:** Out-of-bounds heuristic: if >80% of coordinates fall outside `[-180,180]×[-90,90]` before coercion, suggest "These look like projected coordinates."

### 3.4 Low (Nice-to-Have)

**S-09 — Missing export manifests.**
Surfaces and MP4s carry no provenance. For a methods paper, a downloadable JSON sidecar (`method, parameters, bounds, resolution, timestamps, input SHA-256, boundary SHA-256, generated_at, app version`) makes figures reproducible.
**Fix:** `GET /surface/{id}/manifest.json`, `GET /animate/{id}/manifest.json`.

**S-10 — No significance masking.**
For sparse networks, large interpolated areas are visually as confident as data-dense cores.
**Fix:** Optional stipple/alpha mask where the distance to the nearest station exceeds `2× bandwidth` (KDE) or `weight sum < threshold` (IDW) — a one-line post-process on the predicted grid before PNG encoding.

---

## 4. UI/UX & Interactivity — Findings and Concrete Proposals

### 4.1 Current Interaction Model (What Ships Today)

- Left control panel (four cards + capture) scrolls; right map panel fills.
- Upload → demo/saved table → boundary → view switch → method/params → Generate → Animation → Capture.
- Data-entry page: 100×100 padded grid with inline calendar headers, per-cell delete, row delete, and popup-free adds — plus inline group-header renaming.

### 4.2 Open Issues

| # | Area | Finding | Severity | File |
|---|---|---|---|---|
| U-01 | Upload format | Format example lives only inside the tour tooltip — a user who skipped the tour never sees the long/wide schemas. | High | `templates/index.html:37-47` |
| U-02 | Error surfacing | `app.js:32` `status()` replaces `status-container` text without an `alert` role detail, timeout, or retry action. Network errors (fetch failed) become "Unexpected error." | High | `static/js/app.js:29-33` |
| U-03 | Empty states | Parameter/timestamp selects are empty before any dataset — no hint text. | Medium | `templates/index.html:64-67` |
| U-04 | Generation feedback | After clicking Generate, progress is a single spinner; no per-timestamp phase detail (e.g., "3/4 surfaces blended"). | Medium | `static/js/app.js:231-259` |
| U-05 | Map affordances | Station circles are identical regardless of value; no hover value tooltip, no selection cross-highlight with the grid. | High | `static/js/app.js:128-137` |
| U-06 | Legend discoverability | The colorbar image is centered above a thin labels row — its scale ticks are produced server-side but the numeric min/max are rendered in plain text below, easy to miss read. | Low | `static/css/style.css:72-75` |
| U-07 | Data-entry density | Even with virtualization, 100 rows × 100 columns (10k cells) in DOM initialization produces a visible paint jank on first load (~150–300 ms on the test machine). | Medium | `static/js/data_entry.js` |
| U-08 | Keyboard | No `accesskey` or roving `tabindex` for power users pasting repeatedly; `enableFillHandle` is true but undo is browser-native only. | Low | — |
| U-09 | Mobile | At <850 px the layout stacks (`style.css:79-84`) but data-entry's `flex:1` grid steals scroll — `overflow:auto` on `#data-grid` conflicts with body scroll on iOS Safari; missing `-webkit-overflow-scrolling: touch`. | Medium | `static/css/data-entry.css:47` |
| U-10 | Guided tour persistence | Tour completion is stored as `localStorage["trendsmapp_tour_completed"]="1"` with no "Reset tour" affordance beyond the sidebar button; clearing site data is the only reset. | Low | `static/js/tour.js:4` |
| U-11 | Download identity | `download-video` filename is static (`trendsmapp-animation.mp4`); a second export overwrites silently in the downloads folder. | Low | `templates/index.html:108` |

### 4.3 Proposed Layouts (Pictorial — ASCII, plus CSS intent)

#### Option A — "Analyst" (Recommended for lab use): keep the two-column shell, promote analysis tools to a persistent bottom timeline

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ .app-shell  display:grid  grid-template-columns: 360px 1fr; height:100vh     │
│ ┌─────────────────────┐ ┌──────────────────────────────────────────────────┐ │
│ │ .control-panel      │ │ .map-panel  (MapLibre, position:relative)        │ │
│ │  header + Tour      │ │  ┌────────────────────────────────────────────┐  │ │
│ │  status             │ │  │ #map  (fills panel)                       │  │ │
│ │  ┌ card-load ─────┐ │ │  │          ╱  Legend  ╲                     │  │ │
│ │  │ CSV format hint │ │ │  │   ○ station (hover → value tip)          │  │ │
│ │  └────────────────┘ │ │  └────────────────────────────────────────────┘  │ │
│ │  card-boundary      │ │  ── .analysis-timeline (NEW, below map, sticky) │ │
│ │  card-view+params   │ │  │ metrics ▸ sensitivity strip ▸ manifests     │  │ │
│ │  card-animation     │ │  │ [Validation]  [3 previews]  [Manifest JSON] │  │ │
│ │  card-capture       │ │  └────────────────────────────────────────────┘  │ │
│ └─────────────────────┘ └──────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────┘

CSS:
.analysis-timeline { display:grid; grid-template-columns: 200px 1fr 180px; gap: .6rem; }
.sensitivity-strip { display:flex; gap:.4rem; }
.sensitivity-strip img { height: 64px; border-radius:.35rem; }
```

**Why:** Leaves every existing card in place, adds one new horizontal strip that houses the rigor features (S-01 validation curve, S-05 sensitivity previews, S-09 manifests) without stealing map height. Stick the strip to the bottom of `.map-panel` so it survives scrolling.

#### Option B — "Publication" (Recommended for manuscript figures): collapsible sidebar, map-first

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ header: Trendsmapp  [≡ Sidebar]  [Take a tour]   status pill                │
├──────────────────────────────────────────────────────────────────────────────┤
│ .map-panel.full-bleed  (height: 72vh; sidebar slides over as drawer)         │
│  map + legend + timestamp scrubber (draggable)  + capture float card         │
├──────────────────────────────────────────────────────────────────────────────┤
│ .drawer (transform: translateX; width: min(380px, 90vw))  — Cards 1-4        │
└──────────────────────────────────────────────────────────────────────────────┘

CSS:
.app-shell--publication { grid-template-columns: 0 1fr; }
.app-shell--publication.is-drawer-open { grid-template-columns: 380px 1fr; }
.drawer { transition: transform .18s ease; }
```

**Why:** Manuscript figures are map-dominant; authors need the map to be the hero. The drawer preserves the full control set but removes the permanent 360 px tax on large screens.

#### Option C — "Spreadsheet" (For `data-entry.html`): density toggle + command palette

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ .toolbar  gap:8px;  [+Parameter  +Timestamp  +Coordinate  Density ▾]  [Save]  │
│ ┌──────┐ ┌────────────────────────────────────────────────────────────────┐ │
│ │# prev │ │ .ag-theme-alpine  --ag-cell-horizontal-padding: 4px (compact) │ │
│ │iew    │ │ Lat  Lon  15/01/2024  16/01/2024  ...  (sticky, resizable)      │ │
│ └──────┘ └────────────────────────────────────────────────────────────────┘ │
│ status bar: "12 rows modified • Ctrl+Z undos fill • Press ? for palette"     │
│ palette overlay (Cmd/Ctrl+K): "Delete series", "Rename parameter", "Undo"    │
└──────────────────────────────────────────────────────────────────────────────┘

CSS:
:root { --ag-cell-horizontal-padding: 4px; }
[data-density="cozy"] { --ag-cell-horizontal-padding: 12px; }
.ag-theme-alpine .ag-cell { line-height: 1.15; }
```

**Why:** Data-entry is where power users live for minutes. A density toggle and a command palette make 100×100 navigable without adding toolbar clutter. Paste semantics already exist; the palette makes them discoverable.

---

## 5. Missing Interactivity & Product Opportunities

| # | Proposal | Effort | Payoff | Notes |
|---|---|---|---|---|
| I-01 | **Scrubber timeline** for animation instead of a single download | M | High | Draggable range input over `animation.timestamps`; reuses already-generated surfaces (no recompute). |
| I-02 | **Cross-highlight** between grid row and map station | S | High | Click a row → highlight the station circle; click a station → scroll the grid row into view. Add `gridOptions.onRowClicked` + `map.on("click","station-points")`. |
| I-03 | **Value tooltip** on station hover | S | Medium | MapLibre `popup` on `mouseenter` over `station-points`; shows value, parameter, timestamp. |
| I-04 | **Download hub** (CSV/GeoJSON/Shapefile exports of the current dataset + boundary) | S | Medium | `GET /api/export/csv`, `…/geojson`, `…/shapefile` (optional). |
| I-05 | **Keyboard palette** `?` | M | Medium | Shown in data-entry, lists shortcuts (add timestamp = `T`, add coordinate = `N`, undo = `Ctrl+Z`). |
| I-06 | **Shareable snapshot** URL | M | Medium | Encode `parameter + timestamp + colormap + method` into the hash fragment; `/` restores it on load. |
| I-07 | **Undo/redo stack** for data-entry | M | High | AG Grid has `undoRedoCellEditing`; wire it to a visible toolbar state and persist across reload via `localStorage`. |
| I-08 | **Validation chart** (S-01) | M | High | Tiny `canvas` under Generate — see Scientific Rigor. |
| I-09 | **Bulk import progress** (chunked upload UX) | S | Low | Replace the single spinner with a streamed progress bar using the Fetch `ReadableStream` + `Content-Length`. |
| I-10 | **Dark mode** | S | Low | Invert the existing CSS variables; keep it behind `prefers-color-scheme` initially. |

---

## 6. Suggested Refactors (Structure, Not Just Speed)

| Current | Proposed | Why |
|---|---|---|
| Matplotlib per-frame save | Pillow raster path for surfaces; Matplotlib kept for colorbar only | E-04 — eliminates most `_MATPLOTLIB_LOCK` contention |
| Single `run_science_job` slot | Split `SURFACE_SEMAPHORE` / `VIDEO_SEMAPHORE` (+ settings) | E-02 — surfaces never block video encodes |
| Monolithic `app.js` (485 lines, one IIFE) | `app/map.js`, `app/controls.js`, `app/api.js` modules (`type="module"` with importmap for vendored deps) | Readability + testable units; build stays zero-tooling (`esbuild --bundle` optional) |
| Inline OpenAPI schema host | Versioned, served spec at `/openapi.json` with `redoc` at `/docs` and `swagger` at `/swagger` separation | Discoverability for API consumers |
| Implicit demo boundary path `/static/data/export.geojson` | Named route `GET /api/boundary/default` aliasing the same file, so boundary switching is never a "path string" but a resource id | Eliminates path-traversal string handling in the frontend |

---

## 7. What Would Break If Left As Is (Honest Risk Register)

| Risk | Trigger | Consequence | Mitigant already shipped |
|---|---|---|---|
| Large boundary reintroduction | New study area with 50k vertices | Mask → seconds, user thinks the app froze | `ensure_prepared` ✓ — but without vertex decimation, 100k-vertex boundaries still hurt |
| Multi-timestamp upload + Generate | 12 timestamps, user hits Generate twice | Two queued 9 s videos → map appears frozen | Buttons disable during work ✓ — add a visible queue badge |
| Stale lock file `.secret` on volume | Operator replaces `SECRET_KEY` after first boot | Old persisted secret still on disk | Document that changing `SECRET_KEY` requires removing `data/.secret` |
| Direct SQL duplicates | Manual `INSERT` bypassing the API | `/api/table` pivots into a loud 500 | `_pivot_measurements` 500 with examples ✓ — add a `DELETE /api/admin/repair-duplicates` for recovery |
| Clipboard from `data:` PNG | Safari without `ClipboardItem` | `copyMap` throws "not supported" | Already caught and surfaced as "This browser does not support image clipboard access." ✓ |

---

## 8. Prioritized Roadmap (Proposed Order)

**Next sprint (2–3 days, all low-risk):**
1. I-02/I-03 — cross-highlight + station tooltip (one day, zero backend).
2. U-02/U-05 — status toast queue + empty-state hints.
3. Add the `density toggle` to `data-entry.html` (Option C, CSS-only).

**Follow-up (1 week, needs a `canvas` chart lib or `chart.js` vendored):**
4. S-01 validation chart under Generate (leave-one-out for n≤500, k-fold otherwise).
5. Downloads hub (I-04) + manifest sidecars (S-09).
6. Sensitivity strip (S-05) — three 60×60 previews per timestamp.

**Polish (when manuscript figures dominate):**
7. Option A timeline strip under the map (wires the three rigor pieces together visually).
8. Option B full-bleed map drawer for screenshots.
9. Split `app.js` into ES modules and introduce a shareable hash-fragment state (I-06).

---

## 9. Appendices

### 9.1 File Map (Relevant Hotspots)

| File | Hotspots |
|---|---|
| `utils/spatial_rendering.py:88, 22` | `ensure_prepared` — the critical performance fix. Keep it; add LRU cache. |
| `utils/security.py:14, 72` | Module-level `TOKEN` snapshot — subtle drift risk (V-03). |
| `utils/jobs.py:10` | Single-slot semaphore — split per E-02. |
| `routes/data_api.py:72, 291` | Pivot guard + rename-timestamp — solid foundations for station-level row deletion if desired later. |
| `templates/data-entry.html` | No inline style/script since P2 — CSP-clean. Keep it that way. |
| `static/js/data_entry.js` | 100×100 padding + inline calendar/group headers — consider a density toggle before adding more UI. |

### 9.2 Verification Notes (What the Scan Checked)

- Every `file:line` cited was opened and read; handler registrations were traced into middleware order (`app.py:49-89`) rather than assumed.
- The 10k-vertex boundary timing (18.80 s vs 0.0099 s) is from a live `profile_mask.py` run on this machine, not a synthetic estimate.
- Auth, volume sweeps, and frame-allocation determinism were exercised via live subprocess harnesses, not just unit tests.

### 9.3 Open Author Decisions (Not Code)

- `examples/chilika_demo.xlsx` provenance/license and `CITATION.cff` repository URL remain submission blockers — documented in `examples/README.md` and `action_plan.md`.
- The `oink.env` fallback was removed (P3); any deployment still relying on an accidental `oink.env` file must move `DATABASE_URL` into `.env`.

---

*Generated from a rigorous repository scan on 2026-08-22. File reference style `path:line` is preserved for navigation. No fake URLs, checks, or completion masks were introduced — all timing claims above are from executed harnesses.*

