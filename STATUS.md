# STATUS — Scorched Nebraska

Integrated 2026-09-19 from four branches: `ajeet/foundation-entry-pipeline`,
`arrush/ai-generation`, `rishik/persistence-map`, and the input-layer/geometry
branch that closed steps 03/04/08. Each owner's notes are kept below, unedited
except where a later merge changed a fact.

## What actually works end to end

| Step | Route | State |
| --- | --- | --- |
| 01 geocode | `GET /api/geocode?q=` | Done, verified live |
| 02 footprint | `POST /api/footprint` | Done, verified live |
| 03 photo upload | multipart on `/api/generate-image` | Done |
| 03 photo auto-fetch | `GET /api/photo/mapillary` | Done, verified live |
| 04 World State presets | `GET /api/worldstates`, `POST /api/worldstates/resolve` | Done |
| 05 image edit | `POST /api/generate-image` | Done (Gemini → Kontext fallback) |
| 06 mesh | `POST /api/generate-mesh` | Done (→ placeholder fallback) |
| 07 normalize | `POST /api/mesh/normalize` | Done |
| 08 placement transform | `POST /api/placement` | Done, verified on real 02+07 output |
| 09 correction | `PATCH /api/generations/{id}/correction` | Done |
| 10 propagate | `POST /api/propagate` | Done (reads pre-baked rows) |
| 11 persistence | `/api/generations`, `/api/history` | Done (Supabase or SQLite) |
| 12 map render | frontend | Done |

## The two gaps are closed

Both were filled on the input-layer/geometry branch. The full write-up is in the
last section of this file; the short version:

**Step 04** now serves the five locked descriptions from
`app/services/worldstate.py`. `GET /api/worldstates` returns labels and blurbs
only — no route hands prompt text to the browser, and no route accepts it for the
preset path. `POST /api/worldstates/resolve` turns a selection into the one
string step 05 sends. A freeform override replaces the preset outright.

**Step 08** now computes a real transform. Ground-truth tested on 32 real VT
footprints (rotation recovered to 0.00°, scale to 1.0000, position within 7 cm)
and verified against the real sample data in `assets/samples/`: a live
`POST /api/footprint` → `POST /api/placement` → `POST /api/generations` chain
gives Burruss Hall `scale 1.144`, `scaleXYZ [1.14, 1.14, 2.03]`, `z 0.000`,
`auto-high`, with 18 neighbours checked from step 02's cache.

That fixes the empty map described here previously: rows no longer save with
`Placement`'s `scale: 1` default, so meshes render at building size instead of
roughly one pixel.

One frontend change came with it. `layers.js` `scaleFor` now prefers
`placement.scaleXYZ` when present and falls back to the scalar otherwise — both
real sample meshes need it, because a mesh reconstructed from a single
photograph under-guesses depth by roughly half and the uniform factor alone
leaves the building visibly too shallow on its own footprint.

## Smaller things worth knowing

**Request bodies are camelCase everywhere except `/api/propagate`**, which takes
`source_generation_id` and `radius_meters`. Its frontend caller matches, so
nothing is broken; it is just inconsistent if you are writing a new client.

**`.map-root` needs two-class specificity.** `maplibre-gl.css` is imported from
`MapView.jsx` and therefore lands after `styles.css`; its
`.maplibregl-map { position: relative }` was beating `.map-root { position: absolute }`
on source order and collapsing the map to zero height. Fixed as
`.app-shell > .map-root`. Don't lower that specificity again.

## Integration decisions

Rishik's own merge analysis recommended their modules slot into the foundation
layout rather than the reverse; that is what happened.

- `app/routes/` → `app/routers/`; `app/models.py` folded into `app/models/contracts.py`
  (a module and a package of the same name cannot coexist), re-exported from
  `app/models/__init__.py` so `from ..models import Generation` still works.
- `app/geo.py` → `app/services/geo.py`. Its `meters_per_degree` returns
  `(lat, lng)` while `geo_math.meters_per_degree` returns `(lng, lat)`; the
  formula now lives only in `geo_math` and `geo.py` delegates with a swap, so the
  two can never drift.
- `main.py` mounts routers explicitly instead of auto-discovering them — the
  parallel-agent merge risk it guarded against is over, and explicit mounting
  makes ordering and prefixes visible.
- One config: `app/config.py` is pydantic-settings and carries both the
  entry-pipeline and store fields. `SUPABASE_SERVICE_ROLE_KEY` is accepted as an
  alias for `SUPABASE_SECRET_KEY`.
- One `/api/health`, which now reports the footprint cache *and* store health.
- Frontend is one Vite app: TypeScript with `allowJs`, so the map/panel/correction
  components stay `.jsx` and the contract files stay typed. React pinned to 18.3
  to match the tested deck.gl/MapLibre stack. `App.jsx` → `MapShell.jsx`; the
  entry pipeline mounts inside its left panel via the `entrySlot` prop.
- Requests go through Vite's `/api` proxy, so `VITE_API_BASE_URL` is empty by default.
- Python 3.12 is now required (teammate code uses PEP 604 `X | None`, and
  numpy/scipy pins need 3.11+). The repo previously ran on 3.9.

## Run it

```bash
cd backend && python3.12 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
.venv/bin/python -m uvicorn app.main:app --reload --port 8000
```

```bash
cd frontend && npm install && npm run dev
```

```bash
cd backend && .venv/bin/python -m pytest -q          # unit
cd backend && .venv/bin/python tests/verify_live.py  # live contract checks
cd frontend && npm test
```

---

# STATUS — foundation + entry pipeline (files 01, 02)

Owner: Ajeet. Last updated 2026-09-19.

Covers the project skeleton, `GET /api/geocode` (step 01) and `POST /api/footprint` (step 02).
Everything below that says **decision** is a spot where the spec was silent or the real API
disagreed with it — teammates should read those, because some of them change what you consume.

---

## Status

| Piece | State |
| --- | --- |
| `backend/` FastAPI skeleton, all routers mounted | Done — boots, `/api/health` green |
| `frontend/` Vite + React + TS skeleton | Done — typechecks, runs, drives both routes |
| `GET /api/geocode` (01) | Done — verified live against Nominatim |
| `POST /api/footprint` (02) | Done — verified live against Overpass |
| Teammate routes | Stubbed, return HTTP 501 with a pointer to the spec file |

Tests: 16 unit tests (`pytest tests/`) and 32 live contract checks
(`.venv/bin/python tests/verify_live.py`) — all passing as of 2026-09-19.

## Run it

```bash
cd backend && python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --reload --port 8000
```

```bash
cd frontend && npm install && npm run dev
```

Copy `backend/.env.example` → `backend/.env` and `frontend/.env.example` → `frontend/.env`.
Neither `.env` is committed and neither should ever be.

---

## Blocker resolved: there is no `00b-architecture-contract.md`

The brief named `00b-architecture-contract.md` as the fixed contract for folder structure,
stack, routes and env names. **That file does not exist** — not in `main`, not on any branch,
not in any PR. Confirmed: `00-overview.md` is the contract, and it covers services and build
order but not app structure. The structure below is therefore derived, not handed down. If
anyone has a different structure in flight, say so now and I will move to match it.

### Folder layout

```
backend/
  app/
    main.py                 # FastAPI app, CORS, router mounts
    config.py               # env-backed settings
    models/contracts.py     # Pydantic models = the API contract
    routers/                # geocode, footprint, health, stubs
    services/               # nominatim, overpass, geo_math, cache
  tests/
  requirements.txt
frontend/
  src/types/contract.ts     # mirrors models/contracts.py — change both together
  src/api/client.ts
  src/App.tsx
```

### Routes

Every route is under `/api`. The ones marked *stub* return 501 until their owner fills them in.

| Route | Step | Spec file |
| --- | --- | --- |
| `GET /health` | — | — |
| `GET /geocode?q=` | 01 | `01-geocode-nominatim.md` |
| `POST /footprint` | 02 | `02-footprint-overpass.md` |
| `GET /photo/mapillary`, `POST /photo/upload` | 03 | *stub* |
| `GET /worldstates` | 04 | *stub* |
| `POST /generate/image` | 05 | *stub* |
| `POST /generate/mesh` | 06 | *stub* |
| `POST /mesh/normalize` | 07 | *stub* |
| `POST /placement` | 08 | *stub* |
| `GET /generations`, `POST /generations` | 09/11 | *stub* |
| `POST /propagate` | 10 | *stub* |

### Env var names

Backend (`backend/.env`): `NOMINATIM_USER_AGENT`, `NOMINATIM_BASE_URL`, `OVERPASS_PRIMARY_URL`,
`OVERPASS_MIRROR_URL`, `OVERPASS_BACKOFF_SECONDS`, `MAPILLARY_ACCESS_TOKEN`, `GEMINI_API_KEY`,
`HF_TOKEN`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`.

Frontend (`frontend/.env`): `VITE_API_BASE_URL`, `VITE_SUPABASE_URL`,
`VITE_SUPABASE_PUBLISHABLE_KEY`. Only `VITE_`-prefixed vars reach the browser — no secret keys there.

---

## The one that will bite you: the spec's Overpass query misses real buildings

**`02-footprint-overpass.md` specifies `way["building"](around:50,...)`. That silently returns
nothing for any building mapped as a multipolygon relation.**

Verified: a 250 m way-only pull centred on Torgersen Hall's own geocoded coordinates does not
contain Torgersen Hall at all. It returned Pearson Hall West, 40 m away, with high confidence —
the exact "building growing out of the wrong footprint" failure mode the spec warns about, and
it would have been invisible until a judge was looking at it.

VT buildings confirmed to be relations, i.e. invisible to the spec's query:
**Torgersen Hall, Newman Library, Kelly Hall, Main Eggleston Hall, East Eggleston Hall.**

**Decision:** the query now asks for ways *and* relations, and relation outer member ways are
stitched into a single ring (`_stitch_outer_ring` in `routers/footprint.py`). Torgersen now
resolves correctly: relation 1074689, 175.31 × 72.27 m, bearing 142.16°, 88-point polygon,
query point inside it.

---

## Other decisions where the spec was silent

**Confidence vocabulary is `auto-high` / `auto-low`, not `high` / `low`.**
File 02 says `confidence: "low"`, but files 08, 09 and 11 all use
`auto-high | auto-low | manually-verified`. One vocabulary across the pipeline beats a literal
reading of one file — step 09's UI and step 11's `confidence_state` column need to agree.

**`footprintWidthMeters` / `footprintDepthMeters` are oriented to `rotationDegrees`, not
axis-aligned.** File 02 says "bounding box", but a raw lat/lng box around a building sitting at
45° to the compass reports a near-square: for a real 80 × 40 m building it gives 84.85 × 84.85,
overstating the short axis by more than 2×. Step 08 fits mesh scale to these numbers, so an
axis-aligned box would corrupt every rotated building's scale. The values returned are the
extent *along* the longest-edge bearing and *across* it. Covered by
`test_axis_aligned_box_would_overstate_a_rotated_building`.

**"Multiple equally-close candidates" is now a concrete rule.** In order:
1. Exactly one candidate polygon contains the point → select it, `auto-high`.
2. More than one contains it → `auto-low`, `selected: null`, all candidates returned.
3. None contains it, one candidate within the match radius → select it, `auto-high`.
4. None contains it, nearest two within **5 m** of each other → `auto-low`, `selected: null`.
5. Otherwise the clear nearest → `auto-high`.

`selected` is `null` whenever confidence is `auto-low` and there is real ambiguity. **Step 09:
never fall back to `candidates[0]` when `selected` is null — that is exactly the auto-pick the
spec forbids.** Every response also carries a human-readable `reason`.

**One Overpass query serves both the match and the neighbours.** File 02 says `around:50`;
file 10 wants neighbours out to 250 m *without re-fetching*. The route issues a single 250 m
query and partitions: buildings within 50 m become `candidates`, the rest become `neighbors`.
Steps 08 and 10 should read `neighbors` off the step 02 response rather than calling Overpass.

**Backoff is deferred, not immediate.** File 02 says back off 30 s on 429/406 before retrying.
Sleeping the instant the primary rate-limits would stall the request 30 s while healthy mirrors
sit untried, so: every endpoint gets one attempt first, then the 30 s wait, then only the
rate-limited endpoints are retried. Same policy, roughly a minute faster on a bad day.

**Cache key rounds coordinates to 4 dp (~11 m), keyed with the radius.** In-memory for now;
swap for a Supabase table when step 11 lands if we want it to survive a restart. Verified: a
repeat lookup drops from ~6 s to ~11 ms, and ~5 m of coordinate jitter still hits.

**Geocode "not found" is HTTP 200 with `found: false`**, not a 404 — the spec calls for a
user-facing state, not a crash. A 502 means the *service* failed, and the UI should offer the
click-the-map path.

---

## External APIs behaving differently than documented

**Both spec'd Overpass endpoints were down at the same time** on 2026-09-19:
`overpass-api.de` returned 406, `overpass.kumi.systems` timed out at 40 s, and
`overpass.private.coffee` also timed out. Only `maps.mail.ru` answered (15.7 s). Two endpoints
is not enough margin for demo day, so `OVERPASS_EXTRA_MIRRORS` adds two more, tried in order.
The primary recovered ~10 minutes later. **Pre-cache the demo buildings the night before —
this is not a hypothetical risk, it happened twice during this build.**

**Nominatim 403s repeated direct `curl` calls** even with a correct `User-Agent`, while the same
requests through the app kept working. The app throttles to 1 request/second server-side
(`nominatim_min_interval_seconds`). Don't hammer it from the shell while testing.

---

## Needs a decision from the team

1. **`NOMINATIM_USER_AGENT` still has a placeholder email.** Nominatim's usage policy requires a
   real contact address and blocks generic agents. Someone put a real team address in
   `backend/.env` before demo day.
2. **The cache is in-memory**, so it dies with the server. If we want pre-baked demo buildings to
   survive a restart during judging, step 11's owner and I should agree on a Supabase table.
3. **`README.md` still describes the original Node/Express + `apps/api` + `packages/shared`
   layout**, which is not what we built. I updated the stack and layout sections to match; flag
   it if that collides with anything.

---
---

# STATUS — AI generation: image edit, mesh generation, mesh normalization (files 05, 06, 07)

Last updated 2026-09-19. Code: `backend/app/generation/` + `backend/app/routers/generation.py`.

## State

| Piece | State |
| --- | --- |
| `POST /api/generate-image` (05) | Done. Verified live: real photo → real redesigned PNG in ~33–40 s |
| `POST /api/generate-mesh` (06 + 07) | Done. Verified live: image → normalized textured .glb in ~10–20 s |
| `POST /api/mesh/normalize` (07 standalone) | Done: re-fits an existing .glb, e.g. once the real footprint is known |
| `GET /api/generate/status` | Provider cooldowns + live HF Space states |
| Local TripoSR mesh provider | Done (optional install): same TripoSR model run on this Mac, ~5 s on MPS, no quota |
| Placeholder fallback mesh | Committed: `backend/assets/placeholder.glb`, served at `/assets/placeholder.glb` |
| Real sample outputs | Committed: `backend/assets/samples/` (Burruss Hall, scorched + flooded) |

The foundation's stub paths `/api/generate/image` and `/api/generate/mesh` are served too (same
handlers), and their 501 stubs are removed. Tests, all passing: 24 offline (`pytest`), 14 live
(`pytest -m live`, needs the server running, calls the real Spaces), 1 heavy (`pytest -m heavy`,
local TripoSR through the real route). The foundation's 16 tests still pass on the bumped pins.

## PERSISTENT FAILURES (external, not fixable in our code)

1. **Gemini has no free image quota on our key.** Every image-output model
   (`gemini-2.5-flash-image`, `gemini-3.1-flash-image`, `gemini-3-pro-image`, the `-lite`/`-preview`
   variants, `gemini-omni-*`) returns `429 RESOURCE_EXHAUSTED ... limit: 0`. The allocation is zero,
   not used up. The key itself works (text models answer). So file 00's "Gemini free tier for
   image editing" premise is false today. **Replacement:** FLUX.1 Kontext [dev] via the public HF
   Space `black-forest-labs/FLUX.1-Kontext-Dev` (free, uses `HF_TOKEN`). Gemini stays first in the
   chain; on a `limit: 0` 429 it's skipped for an hour, so it costs ~0.6 s once per hour.
2. **The `stabilityai/TripoSR` Space is broken** (`RUNTIME_ERROR` since its 2026-05-24 rebuild:
   its `torchmcubes` dependency no longer compiles). No call can succeed and no public duplicate is
   running. **Replacement:** `stabilityai/stable-fast-3d` (SF3D), Stability's successor model, which
   outputs a textured `.glb` directly. TripoSR stays first in the chain behind a cached runtime-stage
   check (skipped in ~0 ms while it's down).

3. **Our HF token ran out of Kontext ZeroGPU runs** after ~5 image edits today:
   `AppError: You have exceeded your ZeroGPU runs limit. Subscribe to Hugging Face PRO to get 40 min
   of ZeroGPU quota a day`. SF3D kept working (its runs are cheap). Until the quota refills, uncached
   `/api/generate-image` calls return `502 {retryable: true}` with that message in `attempts`, and
   cached photo+prompt pairs still return instantly. **So generate demo images early and reuse
   them.** A third free image path would need the HF token to have the "Make calls to Inference
   Providers" permission (currently `403` for fine-grained token `ris-011`). Only the account owner
   can change that, and I didn't wire a provider whose response I couldn't capture.

**Mesh-side mitigation, done: local TripoSR.** The mesh chain is `triposr` (Space, skipped while
down) → `sf3d` (Space) → **`triposr-local`** → placeholder. `triposr-local` runs the same open
TripoSR model on this machine (Apple MPS, ~5 s per mesh, no queue, no quota). The only thing that
broke the Space, `torchmcubes`, is swapped for PyMCubes. Its axis convention (+Z up, facade +X)
comes from TripoSR's own camera code and was confirmed by render. Optional install:
`backend/requirements-local-mesh.txt` + one `git clone` (see `app/generation/triposr_local.py`).
Without it the chain skips straight to the placeholder.

Both captured request/response pairs are in files 05 and 06 (CAPTURED EXAMPLE blocks).

## Contract (build against this; Pydantic models in `models/contracts.py`, TS in `types/contract.ts`)

**`POST /api/generate-image`**: `multipart/form-data`: `photo` (file), `worldStatePrompt` (text),
optional `force=true` (skip cache).
→ `200 { imageUrl, sourcePhotoUrl, provider, model, width, height, attempts[], cached, elapsedMs }`.
`imageUrl` is a PNG (the "after" panel); `sourcePhotoUrl` is the EXIF-corrected upload (the "before").
Errors: `400` bad input, `415` not an image, `502`/`504` generation failed/timed out with
`{ detail, retryable: true, attempts }`. Hard budget 60 s (`IMAGE_TIMEOUT_S`).

**`POST /api/generate-mesh`**: JSON, multipart or urlencoded: `imageUrl` (e.g. the generate-image
output) or `image` (file), plus `footprintWidthMeters`, `footprintDepthMeters` from step 02 (optional,
but pass them), optional `force`.
→ `200 { meshUrl, rawMeshUrl, cutoutUrl, confidence: "auto-high"|"auto-low", provider:
"sf3d"|"triposr"|"triposr-local"|"placeholder", fallbackReason, normalization{...}, warnings[], attempts[], cached,
elapsedMs }`. **Never fails for provider reasons.** On failure or timeout (75 s per attempt, retried
once) you get the placeholder, `confidence: "auto-low"` and a `fallbackReason`. `400`/`415` only for
bad input.

**Mesh convention** (details in file 07 and `backend/assets/samples/README.md`): glTF +Y up,
facade faces +Z, meters, sized to the footprint's longest side, base-center pivot at y = 0, walls
squared to X/Z, `NORMAL` included. In deck.gl: `getOrientation [0, yaw, 90]`. **Facade compass
bearing = 180 − yaw** (verified in a real render: yaw 0 → facade south, yaw 90 → east).

Files are served by the backend at `PUBLIC_BASE_URL/outputs/...` (default
`http://localhost:8000`). Set `PUBLIC_BASE_URL` if the frontend reaches the backend at another host.

## Decisions where the spec was silent or wrong

- **Prompt wrapping.** Handing Kontext a bare scene description made it *replace* Burruss Hall with
  a generic house. The World State text is now wrapped as "Edit this photo of a real building. Keep
  the exact same building ... Change only its condition ... to match this scene: {prompt}", after
  which the tower, wings and entrance survive every edit tested. Step 04's preset strings can stay
  pure scene descriptions.
- **Background cutout before image→3D.** SF3D is an object model; a street photo must be cut out
  first. Local `rembg` `birefnet-general` (~5–8 s warm, preloaded at startup, model cached in
  `backend/.cache/`) kept the whole building. `u2net` lost a wing and `isnet` grabbed only the flag.
- **SF3D's Gradio API is misdocumented** by `view_api()`: `/run_button` has hidden Button/State
  inputs, so the documented 5-argument call fails. We seed session state via `/requires_bg_remove`
  and pass all 7 inputs explicitly (see file 06).
- **Normalization squares the mesh up** (photos are taken at an angle; raw meshes sat 22–27° off)
  and **drops floaters using a UV-seam-aware weld**. A plain `split()` treated 829 texture islands
  as "fragments" and would have shredded the surface.
- **Every mesh gets a material and a texture.** Two deck.gl gotchas found in the render harness:
  a glTF primitive with *no material* draws nothing at all in `ScenegraphLayer`, and *vertex colors*
  (`COLOR_0`) are ignored by its PBR shader (flat grey). Normalization now patches in a material for
  any material-less primitive. Local TripoSR's vertex colors are baked into a small per-face
  texture atlas after decimating to 30k faces.
- **Confidence uses the team vocabulary** `auto-high`/`auto-low` (file 06 literally says `"low"`).
- **Caching**: results are content-addressed (`backend/outputs/`, git-ignored) and persisted in
  `outputs/cache.json`, so a repeat request for the same photo + prompt (or image + footprint) is
  instant and survives restarts. Only real generations are cached, never placeholder fallbacks.
- **Dependency pins bumped** in `backend/requirements.txt`: `google-genai` needs `pydantic>=2.12.5`,
  so the foundation's `pydantic==2.10.4` could not stay. FastAPI/uvicorn/pytest now match the
  persistence branch's pins (0.141.1 / 0.53.0 / 9.1.1). Starlette 1.x dropped
  `add_event_handler`, so the startup warmup wraps `app.router.lifespan_context` instead.

## Risks for demo day

- **HF ZeroGPU daily quota (already hit once, see #3).** Both Spaces bill our free `HF_TOKEN`.
  On a quota error the provider goes on a 10-minute cooldown. The mesh route then falls through to
  local TripoSR or the placeholder, and the image route returns 502, retryable. **Pre-generate demo
  buildings early.** Results are cached on disk and replay instantly.
- Public queues: Kontext took 33 s idle and 40 s under light load. Budget is 60 s per the spec.

## Needs a decision from the team

1. If anyone has a Google project with image quota (paid), setting that `GEMINI_API_KEY` makes
   Gemini the live provider with no code change. Otherwise Kontext is the image path.
2. The HF token owner could enable "Make calls to Inference Providers" on the token (free monthly
   credits). That opens a second image path once someone captures its response.
3. Decide which 2-3 demo buildings + World States to pre-generate while Kontext quota is available.

---

# STATUS — persistence + map (files 11, 12, 09, 10)

Owner: Rishik. Last updated 2026-09-19.

## State: all four files implemented, tested, and verified running end to end.

56 tests pass (37 backend pytest, 19 frontend vitest). The map renders real 3D
meshes at real VT coordinates, the correction loop writes back to the database,
and Propagate reveals pre-baked neighbours with the camera pulling out for the
reveal.

---

## BLOCKERS (need a human)

### 1. `SUPABASE_URL` is empty — running on a local SQLite fallback

`backend/.env` and `frontend/.env` both have the **keys** set but the **URL
blank**. The new `sb_secret_…` / `sb_publishable_…` key format does not embed the
project ref, so the URL cannot be derived from the key — it has to be copied from
the dashboard.

**Fix (2 minutes):** Supabase dashboard → Project Settings → Data API → Project
URL (looks like `https://abcdefghijkl.supabase.co`). Paste it into
`SUPABASE_URL` in `backend/.env` and `VITE_SUPABASE_URL` in `frontend/.env`.

**Until then**, nothing is blocked: the store layer auto-selects a local SQLite
file (`backend/local.db`) with an identical schema and identical semantics.
Switching to Supabase is that one env var — no code change. `GET /api/health`
reports which backend is live.

### 2. The `generations` table still has to be created once

PostgREST cannot issue DDL, so this cannot be automated with the keys available.
Paste `backend/sql/001_generations.sql` into the Supabase SQL editor and run it.
It creates the table, the indexes, and a read-only RLS policy for the anon key.

### 3. Waiting on teammates (not blocking my work)

- Real `mesh_url` values from steps 06/07 — every seeded row currently points at
  `frontend/public/placeholder.glb`.
- Real `source_photo` / `artifact` URLs from steps 03/05 — the panel already
  degrades to a "no image" placeholder, so broken URLs do not break the UI.
- Neighbour footprints from step 02 — `POST /api/propagate` accepts an optional
  `neighbors` array and reports any that have no pre-baked row as `pending`.
  Nothing supplies it yet, so `pending` is always empty today.

---

## API contract (build against this)

Base URL is proxied at `/api` from the Vite dev server.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | which store backend is live |
| POST | `/api/generations` | **save one generation** (201) |
| GET | `/api/generations` | every row — the map layer's data |
| GET | `/api/generations/{id}` | one row |
| GET | `/api/history?address=…` | that address's sequence, oldest first |
| PATCH | `/api/generations/{id}/correction` | step 09 write-back |
| POST | `/api/propagate` | step 10 reveal |
| GET | `/api/propagate/radii` | `[50, 100, 250]` |

### POST /api/generations — what steps 01-08 should send

```json
{
  "address": "Burruss Hall, Blacksburg, VA",
  "lat": 37.2287,
  "lng": -80.4229,
  "source_photo": "https://…/original.jpg",
  "artifact": "https://…/redesigned.png",
  "mesh_url": "https://…/building.glb",
  "world_state": "reclaimed",
  "placement": {
    "rotationDegrees": 47.5,
    "scale": 1.83,
    "position": [37.2287, -80.4229, 0.0],
    "confidence": "auto-high",
    "scoredRotationCandidates": [{ "rotationDegrees": 47.5, "iou": 0.81 }]
  }
}
```

Notes:
- `placement` accepts **extra fields** and stores them verbatim — add
  `footprintIoU`, `collisionFlag`, whatever step 08 produces, and persistence
  will not drop it.
- `confidence_state` is optional; it defaults to `placement.confidence`.
- Top-level unknown fields are **rejected with 422** on purpose, so a typo in a
  field name fails loudly instead of silently vanishing.
- `position` is `[lat, lng, z]`. The map converts to deck.gl's `[lng, lat, z]`.

---

## Decisions worth knowing

**One row per generation, never one per address.** No upsert path, no unique
constraint on `address`. The history timeline in the click panel is the visible
proof — Burruss Hall currently shows `reclaimed → flooded → scorched`.

**Write failures are loud.** Every store method raises; nothing returns a falsy
sentinel. Route handlers log `PERSISTENCE FAILURE` and return 502, and the
frontend client throws rather than resolving to `null`. A generation that looks
saved but never persisted would quietly break both history and Propagate.

**Propagate reveals, it does not generate.** Per file 10, clicking Propagate
during judging queries pre-baked rows within the radius that share the source's
World State. Neighbours with no row come back as `pending` and are reported
honestly ("4 revealed · 2 not pre-baked") rather than silently omitted.

**Router auto-discovery.** `app/main.py` mounts every `router` it finds in
`app/routes/*.py`. Drop a file in; do not edit `main.py`. Four of us are working
in parallel and that file would otherwise be a constant merge conflict.

**Esri satellite tiles** are added alongside the keyless OSM raster tiles for the
panel's satellite toggle (file 12 asks for one). Also keyless, attribution
included. OSM stays the default — no MapTiler key anywhere.

---

## Two corrections to file 12, both verified against running code

1. **`scenegraph: d => d.mesh_url` does not work in deck.gl 9.** That prop is
   typed `any` (URL / parsed glTF / Promise), *not* an `Accessor`. Rows are
   grouped by `mesh_url` with one `ScenegraphLayer` per distinct mesh instead.
2. **`roll: 90` is correct and load-bearing.** Verified visually: at `roll: 90`
   buildings stand upright, at `roll: 0` they lie flat. Holds as long as step 07
   keeps emitting Y-up glTF. The left panel has a live axis-check slider if that
   ever changes. Meshes should also carry `NORMAL` or shading goes flat.

---

## Merging with `ajeet/foundation-entry-pipeline` (checked 2026-09-19)

I compared both branches. **The API contract matches — that was the big risk and
it is retired.** Their `Generation` and `PlacementRecord` models use the same
field names, the same `position: [lat, lng, z]` ordering, the same
`confidence_state` values and the same `/api` prefix as mine. Their
`routers/stubs.py` explicitly reserves `/generations` and `/propagate` for this
work with a 501 and a pointer to files 10/11. Nothing needs renegotiating.

What does conflict is **structure, not semantics**. 12 files exist on both
branches:

| Theirs | Mine | Note |
| --- | --- | --- |
| `backend/app/routers/` | `backend/app/routes/` | same idea, different name |
| `backend/app/models/contracts.py` | `backend/app/models.py` | package vs module |
| `backend/app/main.py` | `backend/app/main.py` | they mount explicitly, I auto-discover |
| `frontend/src/**/*.tsx` (TypeScript) | `frontend/src/**/*.jsx` (JavaScript) | — |
| `config.py`, `package.json`, `index.html`, `.env.example`, `.claude/launch.json`, `STATUS.md` | same | straight duplicates |

**Recommended resolution — theirs wins on structure, mine slots in.** They built
the skeleton deliberately, stubs and all, so the lower-friction direction is to
adapt my modules into their layout rather than the reverse:

1. Move `app/routes/generations.py` and `app/routes/propagate.py` into
   `app/routers/`, delete `routers/stubs.py`'s `/generations` + `/propagate`
   entries, and add two `include_router(..., prefix="/api")` lines to their
   `main.py`. My auto-discovery in `main.py` is then redundant — drop it.
2. Move my `models.py` classes into their `models/contracts.py`. The shapes
   already agree; `GenerationCreate`, `Correction` and `propagated_from` are
   additive.
3. `app/store/` and `app/geo.py` are unique to me and conflict with nothing.
   Their `services/geo_math.py` overlaps `app/geo.py` — keep one.
4. Frontend: their `.tsx` and my `.jsx` coexist under one Vite config, but my
   components should be ported to TypeScript to match. Merge the two
   `package.json` dependency lists (they need mine: deck.gl, maplibre-gl,
   loaders.gl).

I have **not** done any of this — it edits their files, and the other two agents
have not pushed yet, so the merge is better done once with everyone's work in
hand.

---

## Running it

```bash
# backend  (http://127.0.0.1:8000)
cd backend && ./.venv/bin/uvicorn app.main:app --reload --port 8000

# demo data — re-run before judging to reset the flagged row
cd backend && ./.venv/bin/python seed/seed_demo.py --reset

# frontend (http://localhost:5173)
cd frontend && npm run dev

# tests
cd backend && ./.venv/bin/python -m pytest -q
cd frontend && npm test
```

Seeded demo: Burruss Hall (3 World States → timeline), 3 pre-baked neighbours at
41m / 90m / 185m, one deliberately `auto-low` row (McBryde Hall) to demo the
correction loop, and Lane Stadium at 420m to prove the radius filter excludes.

---

# STATUS — input layer + geometry core (files 03, 04, 08)

Owner of the Mapillary convenience layer, the World State prompts, and the
placement transform. Everything below is what the next person needs that is not
obvious from the code.

## What landed

| | |
|---|---|
| Step 03 path B | `app/services/mapillary.py`, `app/routers/photo.py`, `frontend/src/photo/PhotoInput.tsx` |
| Step 04 | `app/services/worldstate.py`, `app/routers/worldstates.py`, `frontend/src/worldstate/WorldStateSelector.tsx` |
| Step 08 | `app/services/placement.py`, `app/services/placement_geom.py`, `app/routers/placement.py` |

180 backend tests, 38 frontend. `scripts/placement_preview.py` draws each placed
mesh over its real footprint when a number looks suspicious.

## This branch started in the wrong language

It built the same API surface in Node + Express before the FastAPI foundation
was pushed. Three owners had converged on Python and `routers/stubs.py` left
labelled 501s for exactly these three steps, so the Node version was ported
across and deleted rather than kept as a second backend.

The port is not a rewrite from memory — the Python and TypeScript
implementations were run against the same 29 real footprints and agree on the
min-area-rectangle angle to **0.005°**, and the five prompt strings are
byte-identical.

## Files outside this branch's own modules that changed

Four, all minimal, all listed here so nobody finds them by surprise:

- `app/config.py` — added `mapillary_access_token`. It was already in
  `.env.example` but nothing read it, and `extra="ignore"` meant it vanished.
- `app/main.py` — registered the three new routers.
- `app/routers/stubs.py` — removed the three stubs this branch implemented. The
  router stays for whatever is unimplemented next.
- `frontend/src/map/layers.js` — `scaleFor` prefers `placement.scaleXYZ`, falling
  back to the scalar. See below for why.
- `frontend/src/api/client.ts`, `frontend/src/types/contract.ts`,
  `frontend/src/App.tsx` — added the client calls, types and mounting for the two
  new components.

## Three bugs worth naming, because two of them were invisible

**The test suite could not see the first one.** `polygon-clipping` (the Node
version's boolean-ops library) is CommonJS. Imported as `import * as`, Vite hands
back a callable namespace but Node's ESM interop puts the functions on
`.default` — so **every IoU silently returned 0 under `npm start` while the whole
suite stayed green.** The Python port has no equivalent (Sutherland–Hodgman is
written out in `placement_geom.py`), but the lesson generalises: a green suite
that runs through a different module resolver than production is not proof.

**The rotating-calipers minimum-area rectangle rotated the wrong way.** It used
`+edgeHeading` where aligning an edge with an axis needs `-edgeHeading`, so it
never found the true minimum and was not rotation-invariant. Caught by asserting
the invariant directly: `MAR(rotate(shape, φ)) == MAR(shape) + φ`.

**The scale fit ran in the compass frame.** deck.gl applies
`translate(rotate(scale(model)))` — scale acts on *model-space* axes, before any
rotation — so a non-uniform scale computed against east/north extents stretches
the wrong axes entirely.

## The mesh frame is a rotation, not a mirror — verify this if you touch it

glTF is right-handed. With Y up, the geographic mapping that is a rotation is
**east = +X, north = −Z**. Mapping north to +Z instead reflects the mesh, which
costs IoU on any asymmetric building and is very easy to miss.

Step 07's own note agrees from the other end: *"facade faces south at yaw 0"*,
i.e. +Z points south. Both were checked against real Burruss Hall data by
extruding the real footprint into a mesh in step 07's convention:

| mapping | recovers the baked rotation? | scale | fit quality |
|---|---|---|---|
| north = −Z | yes, at every angle | 1.0000 | 0.9998 |
| north = +Z | no, off by 85° at every angle | 0.98 | **1.0075** |

That `> 1` is the tell. Fit quality is IoU divided by the best a convex outline
*can* score against that polygon, so exceeding 1 is impossible — unless the
shape being compared is not the mesh's real outline. A plain IoU comparison
would not have caught it: on a near-rectangular building the mirrored version
actually scored *higher* (0.79 vs 0.74), which is exactly how this kind of bug
survives a plausibility check.

`test_mesh_frame_is_a_rotation_not_a_mirror` guards it.

## Rotation convention — what `rotationDegrees` means

It is **deck.gl yaw**, ready for `getOrientation` as `[0, yaw, 90]`, because that
is what `layers.js` feeds it. Internally the module works in compass headings and
converts on the way out: `yaw = −heading`, which satisfies step 07's
`facade bearing = 180 − yaw`. The internal heading is in
`diagnostics.headingDegrees` if you need it.

Every `rotationDegrees` in `scoredRotationCandidates` is yaw too, so step 09 can
replay a candidate into the renderer without converting anything.

## Where step 08 deviates from `08-placement-transform.md`

Five places, each measured rather than assumed. All are documented in the code at
the point they happen, and appended to the spec file itself.

**1. Principal axis from the minimum-area rectangle, not the longest edge.** The
mesh base outline is a convex hull; a real OSM footprint usually is not, and a
hull edge bridging a concave notch is long while saying nothing about
orientation. On the real fixtures a polygon and its own hull agree to **0.000°**
on min-area-rectangle angle and disagree by up to **65°** on longest edge. Using
the longest edge put Hancock Hall **29 m** from its footprint and Campbell Hall
**28 m**; the min-area rectangle puts both within **5 cm**. Step 02's
`rotationDegrees` is still accepted, cross-checked and reported.

**2. Candidate headings cancel the mesh's own orientation.**
`heading = footprintAxis − meshAxis + offset`. The spec's literal form assumes
the mesh arrives pointing north; one reconstructed from a photograph does not.
Reduces to the spec's formula when the mesh axis is 0, and the four candidates
stay exactly 90° apart for step 09's buttons.

**3. Confidence judges fit quality, not absolute IoU.** Because the mesh outline
is convex, the ceiling for a given polygon is that polygon against its own hull —
**0.48 for Campbell Hall, 0.98 for Sandy Hall**. One absolute threshold would
flag a perfect placement on the concave buildings and pass a bad one on the
simple ones.

**4. The 180° flip is reported, not flagged.** Comparing winner to runner-up
flagged **44% of real footprints, and every single one was a pure 0-vs-180
pair** — a distinction footprint IoU cannot make, since a footprint is nearly
centrosymmetric. Ambiguity is judged against the best geometrically
*distinguishable* alternative (the 90° turns). `diagnostics.rotationFlipMargin`
is reported so step 09 can still offer "turn it around".

**5. Collision confirms box hits against the real polygons.** The bounding-box
test the spec asks for is kept as the cheap gate, but campus sits at ~45° to the
compass and axis-aligned boxes overlap constantly while buildings are metres
apart. Also, "overlap exceeds a threshold" needs a denominator: against the mesh
alone, a large building completely covering a small neighbour scores ~5% and
passes. It is `max(overlap/mesh, overlap/neighbour)`.

**Added, not in the spec:** an offset refinement. Centroid-matching a convex hull
to a concave footprint is off by a couple of metres; a hill climb on the same IoU
objective recovers it (`diagnostics.refinementShiftMeters`).

## Flags have a severity, and it matters

`low` moves the record to `auto-low`; `info` is recorded but does not. Without
that split the pipeline flags everything: **the single-view depth shortfall fires
on 100% of real meshes**, because guessing depth from one photograph is what
step 06 does, not an anomaly. A confidence signal that fires on every building
tells step 09 nothing.

So `non-uniform-fallback` is `info` unless the aspect distortion exceeds 2.5×
(both real samples are ~1.75×), and `pivot-not-base-centred` is `info` because
placement corrects it exactly. Everything else is `low`.

Confidence is derived from the accumulated flags at the very end, never assigned
as the algorithm goes — spec 08's "don't let one flagged sub-check get silently
overwritten" is structurally impossible here rather than merely avoided.

## For step 09

`scoredRotationCandidates` is the full sorted list of four, each with `iou`,
`scale` and `coverage` — nothing discarded. `flags[]` carries `subStep` of
`footprint | rotation | scale | collision | ground | mesh`, so the UI can tell a
step-02 footprint problem from a step-08 placement problem, and `severity` so it
can show the informational ones differently from the ones that actually demand a
human.

## Mapillary: the index is non-deterministic

Five **byte-identical** requests to a known-dense area returned **0, 2, 5, 6, 5**
images. A single empty `data` array is frequently a false negative. Handled with
a retry ladder (40 m, 40 m again, then one 100 m pass), de-duplicated by id and
ranked by true distance. Widening is last and modest on purpose: imagery 100 m
away may be of a different building, and this photo feeds image generation.

Blacksburg coverage is real — Burruss Hall returns captures ~23–45 m away, most
recent 2026-03-14. The full capture and the field notes (`geometry.coordinates`
is `[lng, lat]`; `captured_at` is epoch **milliseconds**; `thumb_*_url` is a
signed expiring CDN URL that must not be persisted) are appended to
`markdown_files/03-photo-input.md`.

## Two things for other owners, not fixed here

**Step 02 / Overpass returns 406 without a real `User-Agent`.** Plain `curl` got
`406 Not Acceptable`; the identical request with
`User-Agent: ScorchedNebraskaVTHacks/1.0 (...)` got `200`. Spec 02 attributes
406s to load, but at least some are just the missing header. `overpass-api.de`
also 429s readily; `overpass.kumi.systems` worked every time it did not. The
router already handles both — worth knowing when one fails by hand.

**Step 06/07: `burruss_scorched.glb` comes out ~64.5 m tall.** Burruss is roughly
30 m. Step 07 scales the longest horizontal side to the footprint and height
follows proportionally, so a mesh that is too tall for its plan stays too tall.
Placement reports it as `diagnostics.scaledHeightMeters` rather than correcting
it, because height is step 07's to own and silently rescaling it would hide the
problem. `burruss_flooded.glb` is fine at 40.6 m. Worth picking the flooded one
for the demo, or regenerating the scorched mesh.

## Left undone

- **The generate flow is not wired end to end in the UI.** `App.tsx` mounts the
  photo input and the World State selector under the entry panel and holds their
  state, but nothing calls `generateImage` → `generateMesh` → `computePlacement`
  yet. Each piece works on its own and over HTTP; the chaining is a UI job that
  belongs with whoever owns the pipeline panel.
- **`generateImage` in `client.ts` still takes a raw `worldStatePrompt` string.**
  Nothing calls it, so no raw preset text is reaching step 05 today. When the
  flow is wired, call `resolveWorldStatePrompt` first and pass its result.
