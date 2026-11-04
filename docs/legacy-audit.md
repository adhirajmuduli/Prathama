# Legacy prototype audit (Phase 0)

Scope: the pre-rebuild prototype that occupies the repository root at the time
of this audit (`app.py`, `config.py`, `db.py`, `routes/`, `utils/`, `templates/`,
`static/`, root `tests/`).

Audited revision: `bc816c8` plus the freeze fixes listed in
[§6](#6-defects-found-and-fixed-during-the-freeze).

Purpose: freeze the prototype so it stays reproducible for comparison while the
replacement in `backend/` and `frontend/` is built, and record which legacy
behavior must survive the rewrite. Per the rebuild plan, the legacy application
is a behavioral reference only; no legacy production code is copied into the new
implementation.

---

## 1. Runtime surface

| Entry point | Legacy content | Disposition |
|---|---|---|
| `app.py` | FastAPI app factory, static mount, `/`, `/api/health`, `/api/config`, `/api/demo`, `/upload`, `/upload-boundary`, `/generate-heatmap`, `/legend/{timestamp}.png` | Not migrated. Replaced by `backend/src/trendsmapp/api/`. |
| `routes/data_api.py` | `/data-entry`, `/api/parameters`, `/api/timestamps`, `/api/table` (GET/POST), `/api/measurement`, `/api/table/delete-station`, `/api/table/delete-series`, `/api/table/rename-parameter`, `/api/table/rename-timestamp`, `/api/export-dataset` | Not migrated. Database-backed spreadsheet editing is out of scope for the rebuild; the data-entry plane is replaced by the upload → mapping → QC pipeline. |
| `routes/animation_api.py` | `POST /api/animate` | Not migrated. Replaced by the analysis + animation job workflows. |
| `db.py` | Async SQLAlchemy engine over SQLite/PostgreSQL, `Station`, `Parameter`, `Measurement` tables, `create_all` bootstrap | Not migrated. Replaced by Alembic-managed metadata tables (`backend/migrations/versions/0001_initial.py`). |
| `config.py` | Dataclass settings parsed from environment | Not migrated. Replaced by `backend/src/trendsmapp/settings.py` (Pydantic settings, validated at startup). |
| `utils/security.py` | Token auth dependency, path guard, request-body cap, security headers | Partially preserved as design intent only. The rebuild replaces session-bound file paths with opaque artifact IDs and adds trusted-host/CORS/rate-limit controls. |
| `utils/jobs.py` | In-process semaphores bounding surface/video jobs | Not migrated. The rebuild moves job execution to a PostgreSQL-backed worker pool. |
| `utils/storage.py` | Upload replacement and TTL sweep on the local filesystem | Not migrated. Replaced by the content-addressed storage adapters in `backend/src/trendsmapp/storage/`. |
| `utils/datasets.py` | Shared dataset envelope, secure filename helpers | Not migrated. The envelope is replaced by versioned dataset contracts. |
| `utils/data_processing.py` | Long/wide table normalization, UTC timestamps | Preserved as a **behavioral specification** only. The rebuild re-implements it as typed normalization stages with explicit mapping, unit conversion, qualifiers, and duplicate policy. |
| `utils/spatial_rendering.py` | Boundary loading/repair, IDW, Gaussian KDE, PNG + colorbar rendering | Behaviorally preserved (IDW semantics, boundary preparation, masking). KDE is **not** carried over: the rebuild treats KDE as a density estimator, not a measurement interpolator. |
| `utils/animation_generator.py` | Observed-surface blending, gap-proportional frame allocation, H.264 encoding | Preserved as a behavioral specification (gap-proportional pacing, observed/interpolated labels). The rebuild encodes from stored rasters rather than recomputing surfaces inside the video loop. |
| `templates/`, `static/` | Jinja pages, MapLibre GL front end, AG Grid data-entry sheet, guided tour | Not migrated. The rebuild ships a typed Next.js application in `frontend/`. |
| `tests/` | 73 tests over the prototype | Preserved in place as the frozen reference suite. The rebuild has its own suite under `backend/tests/` and `frontend/`. |

### 1.1 Legacy HTTP contract (frozen reference)

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Map/analysis page (protected when a token is configured) |
| GET | `/data-entry` | Spreadsheet data-entry page |
| GET | `/api/health` | Liveness probe; public; discloses no version |
| GET | `/api/config` | Public configuration, limits, method list |
| GET | `/api/demo` | Load the bundled example workbook |
| POST | `/upload` | CSV/XLSX/XLS upload → normalized dataset envelope |
| POST | `/upload-boundary` | GeoJSON boundary upload → session-bound path |
| POST | `/generate-heatmap` | IDW/KDE surface PNGs for selected timestamps |
| GET | `/legend/{timestamp}.png` | Matplotlib colorbar PNG |
| POST | `/api/animate` | Session-bound MP4 animation |
| GET/POST | `/api/table`, `/api/parameters`, `/api/timestamps` | Spreadsheet data plane |
| POST/DELETE | `/api/measurement`, `/api/table/*` | Spreadsheet mutations |

---

## 2. Scientific behavior worth preserving

These are the properties the rebuild must keep, with the reason each exists.

1. **Explicit column roles.** Coordinate aliases (`lat`, `lon`, `lng`, `x`, `y`)
   are accepted; positional guessing is forbidden. A missing role is an error,
   never an inference.
2. **Blank versus malformed distinction.** Blank wide-form cells mean "not
   sampled" and are dropped; non-blank malformed cells reject the upload.
   The rebuild keeps this and adds explicit `value_qualifier` handling.
3. **UTC canonicalization.** Timestamps are stored as `YYYY-MM-DDTHH:MM:SSZ`.
   The rebuild adds a declared date-order policy and rejects ambiguous dates
   rather than guessing.
4. **Parameter-blind surface rejection.** A surface request must resolve to
   exactly one parameter; colocated values of different analytes are never
   averaged. This defect (mixed-parameter averaging) existed in the prototype
   and was fixed before the freeze; the rebuild enforces it per parameter and
   timestamp.
5. **Projected-distance interpolation.** Surfaces are computed from an
   equirectangular kilometre projection centred on the boundary, never from
   raw degrees. The rebuild replaces this with a proper projected CRS
   (PyProj) because the regional approximation is not adequate for kriging or
   GP kernels.
6. **Prepared boundary geometry.** `shapely.prepare` before `contains_xy` is
   mandatory: unprepared point-in-polygon against the 10,089-vertex Chilika
   coastline cost ~18.4 s per surface versus 0.0099 s prepared, with
   bit-identical output. The rebuild keeps prepared geometries and adds a
   regression test for equivalence.
7. **Gap-proportional animation pacing.** Transition frames are distributed
   across observed intervals in proportion to elapsed time using deterministic
   largest-remainder rounding, so playback speed reflects the real calendar.
   Every interval receives at least one frame.
8. **Observed versus interpolated disclosure.** Every rendered frame carries
   its timestamp and an explicit `Observed` / `Interpolated` status label.
9. **Bounded, structured failures.** Upload, surface, and animation failures
   return actionable messages; the surface and animation paths never raise
   unhandled 500s for scientific input errors.
10. **CPU work off the event loop.** Parsing, interpolation, Matplotlib
    rendering, and encoding run in worker threads bounded by semaphores.

---

## 3. Security posture at the audited revision

| Control | Legacy implementation | Rebuild disposition |
|---|---|---|
| Shared-secret auth | `TRENDSMAPP_AUTH_TOKEN`; Bearer / Basic / `X-Trendsmapp-Token`; `/api/health` public | Replaced by opaque artifact IDs, per-job idempotency, and rate limiting. |
| Request body cap | `BodyLimitMiddleware` rejects declared and streamed oversize bodies before parsing | Preserved, with a stricter per-endpoint limit and a separate upload-part limit. |
| Security headers | Self-origin CSP, `nosniff`, `DENY` framing, strict referrer policy | Preserved and extended; moved to the frontend host with Netlify headers. |
| Upload path safety | UUID-prefixed names, allowlisted parent directories, no user-controlled paths | Preserved and strengthened: storage keys are derived from IDs and hashes only. |
| Session binding | Uploaded file name stored in the signed cookie session | Replaced: the session stores opaque IDs only, never paths or filenames. |
| Resource ceilings | Upload bytes, observation rows, timestamps, stations per frame, video frames, grid resolution | Preserved and extended to grid cells, model candidates, search trials, SHAP rows. |

Legacy weaknesses that are **not** carried over: signed-cookie file binding,
in-process job slots, filesystem TTL sweeping instead of object-store retention,
and a single global token for every data and compute route.

---

## 4. Data and boundary provenance

### 4.1 Default lagoon boundary — `static/data/export.geojson`

| Field | Value |
|---|---|
| Feature | OpenStreetMap relation `1917079`, `name=Chilika Lake`, `natural=water`, `type=multipolygon` |
| Source | <https://www.openstreetmap.org/relation/1917079> |
| Generator | overpass-turbo |
| Retrieved | `2025-07-03T11:02:23Z` (embedded `timestamp` property) |
| License | ODbL 1.0 (`copyright` property: "The data included in this document is from www.openstreetmap.org. The data is made available under ODbL.") |
| Geometry | one `Feature`, MultiPolygon, 847,454 bytes |
| SHA-256 | `6a18811f70f56e4f4b3455b6e376470da447483821faeaef93147fc0100b9775` |

The source and reuse rights are known, so the boundary may be used as the
versioned `default_boundary.geojson` resource in the rebuild, with the ODbL
attribution preserved in the resource metadata and in every export bundle.

### 4.2 Example workbook — `examples/chilika_demo.xlsx`

33 stations × 12 monthly columns → 395 normalized observations; SHA-256
`ebfa146ad0040b41d3bb5713dba96956c6ce788eb71adf8e57b1a2357d0d7030`.

The authoritative source URL, creator, collection protocol, analyte
definition/unit, and dataset-specific reuse license are **not** recorded. The
workbook is valid as a software fixture and must not be described as an
open real-world dataset. Before manuscript use it must either gain complete
provenance or be replaced by a documented synthetic generator with a recorded
seed. This blocks publication, not the software build.

### 4.3 Repository hygiene defects

| Item | Problem | Action |
|---|---|---|
| `.secret` | A generated session secret was committed in `93ded34` and is still tracked, although `.gitignore` lists it. | Remove from version control during archive; rotate the value. |
| `Screen Recording 2026-08-31 114655.mp4` | 17.8 MB screen recording committed to the repository and currently deleted in the working tree. | Keep deleted; do not restore. |
| `examples/Testfile.xlsx` | Duplicate of the bundled workbook tracked as a test artifact. | Convert to explicit fixtures under `backend/testdata/` during Phase 2, then drop. |

---

## 5. Deferred, out-of-scope legacy features

The rebuild does not carry over: the AG Grid spreadsheet data-entry plane, the
guided tour, the client-side MapLibre surface display, the KDE "interpolator",
the shared-secret authentication scheme, and the demo workbook auto-loader.
Each is replaced by a versioned, server-derived workflow in the rebuild plan.

---

## 6. Defects found and fixed during the freeze

The prototype at `bc816c8` did **not** have a passing test suite; the archive
could not be used as a comparison baseline until these were repaired.

| # | Defect | Location | Repair |
|---|---|---|---|
| F-1 | The spatial-rendering test module failed to import: the `_boundary` fixture helper had been replaced by a dangling `return` statement at module scope, so the whole module raised `SyntaxError` and pytest aborted collection. | `tests/test_spatial_rendering.py` | Restored the helper so it writes the polygon fixture and returns the prepared geometry (`load_boundary(path)[0]`). |
| F-2 | The shared `client` fixture required an `auth_token` fixture that was defined only inside `tests/test_security_and_limits.py`, so 35 tests errored during setup with `fixture 'auth_token' not found`. | `tests/conftest.py` | Moved the `auth_token` fixture into `conftest.py` and removed the bogus dependency from `client`. Authentication stays opt-in per test. |
| F-3 | Two tests requested `auth_token` but sent no credentials, so they asserted against 401 responses (`KeyError: 'data'` and a legend 401). | `tests/test_security_and_limits.py` | Send the `Authorization: Bearer` header, matching the established pattern in the same module. |
| F-4 | `utils/spatial_rendering.py` contained a duplicated `ensure_prepared` definition (identical body, defined twice). | `utils/spatial_rendering.py` | Not changed during the freeze; the rebuild implements geometry preparation once in `backend/src/trendsmapp/geospatial/`. |

After the repairs the frozen prototype suite is green: **73 passed** on
Python 3.10.6.

---

## 7. How to run the frozen prototype

```powershell
py -3.10 -m venv .venv
.venv\Scripts\python.exe -m pip install --requirement requirements.lock.txt
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000
```

The prototype listens on `http://127.0.0.1:8000`, serves `/docs`, and exposes
the legacy routes listed in §1.1. It is frozen: only defect repairs against
the frozen contract are accepted, and no new scientific capability is added
here. All new capability lands in `backend/` and `frontend/`.
