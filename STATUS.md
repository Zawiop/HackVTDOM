# STATUS — Scorched Nebraska

Integrated 2026-09-19 from three branches: `ajeet/foundation-entry-pipeline`,
`arrush/ai-generation`, `rishik/persistence-map`. Each owner's notes are kept
below, unedited except where the merge changed a fact.

## Frontend consolidated to TypeScript (2026-09-19, latest change)

The map half had been bridged into the TS app through a `MapShell.jsx` shim,
which left the frontend half JavaScript and half TypeScript: two API clients
(`lib/api.js` and `api/client.ts`), two stylesheets (`styles.css` and
`index.css`), and `.jsx` components beside `.tsx` ones. That is now one
TypeScript tree:

- `MapShell.jsx` / `MapShell.d.ts` are gone; `App.tsx` composes the map and the
  panels directly.
- `lib/api.js` merged into `api/client.ts`, which now holds every endpoint —
  geocode, footprint, generate-image, generate-mesh, and the persistence and
  propagate calls. `ApiError` carries `status` and `path` so callers can branch.
- `styles.css` merged into `index.css`; `main.tsx` imports one stylesheet.
- All map, panel, correction and propagate components are `.tsx`; their tests
  are `.ts`.
- `types/contract.ts` matches the backend again: `Generation.id` and
  `created_at` are non-null (every stored row has both), `placement` is
  non-null, and `GenerationCreate`, `Correction`, `PropagateResponse` and
  `PlacementOverrides` are declared.

Two behaviours came with it:

- **Clicking the map runs step 02 for that point**, which closes the
  "click the map once step 12 lands" TODO. Clicking an *existing* building
  selects it instead and deliberately does **not** fire an Overpass query —
  Overpass is the most fragile dependency we have.
- **Step 02's cached `neighbors` are passed straight into propagate**, so it
  never re-fetches them.

One CSS trap worth knowing: MapLibre's stylesheet sets
`.maplibregl-map { position: relative }` on the same element as `.map-root`,
and it is imported after `index.css`. An unqualified `.map-root` rule loses the
cascade and the map collapses to **zero height** while still reporting full
width — with no error anywhere. The rule is written `.app-shell .map-root` to
win on specificity rather than depend on import order.

Verified after the change: 77 backend tests, 19 frontend tests, clean
`tsc -b && vite build`, and a browser pass over geocode, map-click footprint,
3D placement, the correction loop and propagate.


## What actually works end to end

| Step | Route | State |
| --- | --- | --- |
| 01 geocode | `GET /api/geocode?q=` | Done, verified live |
| 02 footprint | `POST /api/footprint` | Done, verified live |
| 03 photo upload | multipart on `/api/generate-image` | Done (Mapillary auto-fetch not built) |
| 04 World State presets | `GET /api/worldstates` | **Not built — 501** |
| 05 image edit | `POST /api/generate-image` | Done (Gemini → Kontext fallback) |
| 06 mesh | `POST /api/generate-mesh` | Done (→ placeholder fallback) |
| 07 normalize | `POST /api/mesh/normalize` | Done |
| 08 placement transform | `POST /api/placement` | Done, IoU rotation search |
| 09 correction | `PATCH /api/generations/{id}/correction` | Done |
| 10 propagate | `POST /api/propagate` | Done (reads pre-baked rows) |
| 11 persistence | `/api/generations`, `/api/history` | Done (Supabase or SQLite) |
| 12 map render | frontend | Done |

## The remaining gap

**Step 04 (World State presets) is not implemented.** The frontend sends raw
`worldStatePrompt` text for every generation. `04-worldstate-prompts.md` says the
five presets must live server-side so output stays consistent across buildings and
users, and that the frontend must not send raw prompt text for the preset path.
Right now nothing enforces that.

## Step 08 — how the transform is computed

`POST /api/placement` takes the chosen polygon and neighbours from step 02 plus
the mesh's `normalization.extentsMeters` from step 07. No external calls; it never
re-queries Overpass.

**The mesh footprint is modelled as its normalized width x depth rectangle**, not
its true base outline. TripoSR-class meshes are single-image reconstructions with
noisy bases, so a rectangle is both steadier and enough to rank four rotations
against a real polygon. It also means the IoU search cannot tell a facade from its
back: the 0/180 and 90/270 candidates score identically by construction. That is
reported in `rotation_note`, and picking a facade is left to the human in step 09,
which is where the spec already puts it.

**Rotation** scores the longest-edge bearing at +0/90/180/270. All four are
returned with their IoU and their own best scale, because step 09 replays them as
"try these alignments" buttons.

**The fit test is relative, not absolute.** A rectangle can never cover an L-shaped
or bridged building, so the achievable IoU is capped by how rectangular the
footprint is. The response carries `rectangularity` (polygon area over its oriented
bounding box) and the rotation passes when the best candidate reaches 80% of that
ceiling. A flat IoU threshold flagged Torgersen Hall — whose bridge over Alumni Mall
caps it at 0.42 — even though its best rotation was 96% of everything achievable.
Below 35% rectangularity the shape is too irregular for a rectangle to orient at
all, and it goes straight to a human.

**Scale** is uniform, fitted with `min()` so the mesh stays inside the real
footprint, which also keeps the collision test honest. When proportions disagree by
more than 30% the uniform factor still populates `scale` — proportion-preserving is
the stated preference — and a non-uniform `scaleXYZ` is offered alongside it.
**Step 12 currently renders `scale` only; read `scaleXYZ` when it is not null.**

**Collision uses real polygon intersection, not axis-aligned bounding boxes.**
File 08 says bounding box, but axis-aligned boxes around two diagonal buildings
overlap heavily even when the buildings do not touch — on this campus that flagged
almost everything, including a spurious 45% "overlap" for Torgersen. The placed
mesh is a convex rectangle, so the true intersection is one clip away.

**Every sub-check is reported separately** in `checks`, and one flag is never
overwritten by a later clean check. An `auto-low` footprint from step 02 stays
`auto-low` through placement.

Verified against real buildings: Burruss Hall resolves to 137.07 deg at 86% of its
achievable fit; Torgersen Hall to 142.16 deg at 96%.

## Demo data now uses real coordinates

The seeder previously placed rows at synthetic offsets from Burruss. Once step 08
started matching against real OSM footprints those offsets resolved to whichever
building was actually there — the row labelled "Williams Hall" was sitting on
**Patton Hall**, and both "Newman Library" and "McBryde Hall" landed on **Holden
Hall**. The fixtures are now the real geocoded coordinates.

**One consequence to know before the pitch:** VT buildings are more than 100 m
apart centre-to-centre, so Propagate only reveals anything at the 250 m radius —
the 50 m and 100 m tiers are honestly empty. The synthetic offsets had been hiding
this. Either demo at 250 m, or change step 10 to measure the radius edge-to-edge
rather than centroid-to-centroid, which is arguably the more correct reading of
"buildings within 50 m" for buildings that are themselves 100 m wide. That needs
footprint polygons per row, which the `generations` table does not store today.

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
| `POST /api/generate-image` (05) | Done. Three providers; verified live: real photo → real redesigned PNG in ~12–40 s |
| `POST /api/generate-mesh` (06 + 07) | Done. Verified live: image → normalized textured .glb in ~10–20 s |
| `POST /api/mesh/normalize` (07 standalone) | Done: re-fits an existing .glb, e.g. once the real footprint is known |
| `GET /api/generate/status` | Provider cooldowns + live HF Space states |
| Local TripoSR mesh provider | Done (optional install): same TripoSR model run on this Mac, ~5 s on MPS, no quota |
| Entrances (doors marked on the mesh) | Done: doors detected in the image, baked in as glowing portals + returned as data |
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
   Providers" permission. **Resolved 2026-09-19:** the permission is now enabled on the team token,
   its contract is captured in file 05, and it is wired in as the third image provider
   (`hf-inference`). It draws on the token's *monthly credits*, a different pool from the Space's
   *daily* ZeroGPU quota, so it still answers when the Space is exhausted — and it was ~3x faster
   (11.9 s vs 34 s) in testing. It is last in the chain because the daily pool is the bigger one.

**Mesh-side mitigation, done: local TripoSR.** The mesh chain is `triposr` (Space, skipped while
down) → `sf3d` (Space) → **`triposr-local`** → placeholder. `triposr-local` runs the same open
TripoSR model on this machine (Apple MPS, ~5 s per mesh, no queue, no quota). The only thing that
broke the Space, `torchmcubes`, is swapped for PyMCubes. Its axis convention (+Z up, facade +X)
comes from TripoSR's own camera code and was confirmed by render. Optional install:
`backend/requirements-local-mesh.txt` + one `git clone` (see `app/generation/triposr_local.py`).
Without it the chain skips straight to the placeholder.

Both captured request/response pairs are in files 05 and 06 (CAPTURED EXAMPLE blocks).

## Entrances — doors marked on every mesh (added after the original specs)

`/api/generate-mesh` now finds the building's doors and marks them, so the world has places to
walk into. Doors are detected in the generated image with **OWLv2** (open-vocabulary, runs
locally, no quota, ~0.5 s warm), kept only when they sit on the building and reach near its base,
then projected onto the mesh by replaying each mesh model's own input crop and camera and
raycasting. Each one is baked into the `.glb` as a **glowing portal** and returned as data:

```json
"entrances": [{ "id": 0, "isMain": true, "position": [-12.261, 7.87, 16.793],
                "facing": [-0.1185, 0, 0.993], "widthMeters": 6.83, "heightMeters": 8.29,
                "score": 0.43, "imageBox": [406, 532, 481, 623],
                "source": "detected", "confidence": "auto-high" }]
```

Same frame as the mesh, so entrances follow it through step 08 (rotate by the placement yaw,
scale, offset to lat/lng). Every building gets at least one: with no detection, a
`source: "default"` door goes at the facade front-center, flagged `auto-low`. Verified on real
Burruss Hall output: the arched tower entrance is found in the photo, the scorched render and the
flooded render (scores 0.39-0.44), and lands on the tower in a real deck.gl render.

Two things worth knowing if you touch this:
- **`KHR_materials_unlit` is what makes it glow.** A plain emissive PBR material renders
  washed-out pale tan in deck.gl; unlit gives full-brightness amber. Both are set, so renderers
  without the extension still get the emissive fallback.
- **Portals are separate geometry** inside the `.glb` (`entrance_<id>_frame` / `_glow`), and
  `normalization.extentsMeters` still measures the building alone, so step 08 is unaffected.

Needs `requirements-local-mesh.txt` (torch + transformers, OWLv2 ~600 MB on first use). Without
it every building just gets the default front-center entrance.

## Contract (build against this; Pydantic models in `models/contracts.py`, TS in `types/contract.ts`)

**`POST /api/generate-image`**: `multipart/form-data`: `photo` (file), `worldStatePrompt` (text),
optional `force=true` (skip cache). Providers in order: `gemini` (no free image quota today),
`kontext` (HF Space, daily ZeroGPU quota), `hf-inference` (same model via HF Inference Providers,
monthly credits). A provider that reports a quota error is skipped for 10 minutes.
→ `200 { imageUrl, sourcePhotoUrl, provider, model, width, height, attempts[], cached, elapsedMs }`.
`imageUrl` is a PNG (the "after" panel); `sourcePhotoUrl` is the EXIF-corrected upload (the "before").
Errors: `400` bad input, `415` not an image, `502`/`504` generation failed/timed out with
`{ detail, retryable: true, attempts }`. Hard budget 60 s (`IMAGE_TIMEOUT_S`).

**`POST /api/generate-mesh`**: JSON, multipart or urlencoded: `imageUrl` (e.g. the generate-image
output) or `image` (file), plus `footprintWidthMeters`, `footprintDepthMeters` from step 02 (optional,
but pass them), optional `force`. Also returns `entrances` (see above).
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
- **A blank key in `.env` now means "not set".** `HF_TOKEN=""` used to go out as an invalid
  `Authorization: Bearer ` header and every HF Space call failed with `LocalProtocolError`
  instead of falling back to anonymous access. Same for `GEMINI_API_KEY`.
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
