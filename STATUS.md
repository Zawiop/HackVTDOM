# STATUS — Scorched Nebraska

Merged branch: `ajeet/foundation-entry-pipeline` (files 01, 02, skeleton) +
`rishik/persistence-map` (files 09, 10, 11, 12). Last updated 2026-09-19.

Steps 03-08 are still stubs returning HTTP 501 with a pointer to their spec file.

---

## What runs today

| Piece | State |
| --- | --- |
| FastAPI skeleton, all routers mounted | Done |
| `GET /api/geocode` (01) | Done — verified live against Nominatim |
| `POST /api/footprint` (02) | Done — verified live against Overpass |
| `POST/GET /api/generations`, `GET /api/history` (11) | Done |
| `PATCH /api/generations/{id}/correction` (09) | Done |
| `POST /api/propagate` (10) | Done |
| MapLibre + deck.gl 3D map, click panel (12) | Done |
| Steps 03-08 | Stubbed, HTTP 501 |

Tests: **53 backend** (`pytest`) + **19 frontend** (`npm test`) = 72, all
passing. Plus 32 live contract checks in `backend/tests/verify_live.py`.

### Run it

```bash
cd backend && python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --reload --port 8000
```

```bash
cd frontend && npm install && npm run dev
```

```bash
# demo data — re-run before judging to reset the flagged row
cd backend && .venv/bin/python seed/seed_demo.py --reset
```

Copy `backend/.env.example` → `backend/.env` and `frontend/.env.example` →
`frontend/.env`. Neither `.env` is committed and neither should ever be.

---

## BLOCKERS (need a human)

### 1. `SUPABASE_URL` is empty — running on a local SQLite fallback

`backend/.env` and `frontend/.env` both have the **keys** set but the **URL
blank**. The `sb_secret_…` / `sb_publishable_…` key format does not embed the
project ref, so the URL cannot be derived — it has to be copied from the
dashboard.

**Fix (2 minutes):** Supabase dashboard → Project Settings → Data API → Project
URL (looks like `https://abcdefghijkl.supabase.co`). Paste into `SUPABASE_URL`
in `backend/.env`.

**Until then nothing is blocked:** the store auto-selects a local SQLite file
(`backend/local.db`) with an identical schema and identical semantics.
Switching is that one env var — no code change. `GET /api/health` reports which
backend is live.

### 2. The `generations` table still has to be created once

PostgREST cannot issue DDL. Paste `backend/sql/001_generations.sql` into the
Supabase SQL editor and run it. It creates the table, the indexes, and a
read-only RLS policy for the anon key.

### 3. `NOMINATIM_USER_AGENT` still has a placeholder email

Nominatim's usage policy requires a real contact address and blocks generic
agents. Put a real team address in `backend/.env` before demo day.

### 4. Waiting on steps 03-08

Real `mesh_url`, `source_photo` and `artifact` values. Every seeded row points
at `frontend/public/placeholder.glb`, and the panel degrades to a "no image"
placeholder, so nothing breaks in the meantime.

---

## API contract

Every route is under `/api`. Models live in `backend/app/models/contracts.py`
and are mirrored field for field in `frontend/src/types/contract.ts` — **change
one, change the other.**

| Route | Step | State |
| --- | --- | --- |
| `GET /health` | — | reports store backend + footprint cache size |
| `GET /geocode?q=` | 01 | done |
| `POST /footprint` | 02 | done |
| `GET /photo/mapillary`, `POST /photo/upload` | 03 | stub |
| `GET /worldstates` | 04 | stub |
| `POST /generate/image` | 05 | stub |
| `POST /generate/mesh` | 06 | stub |
| `POST /mesh/normalize` | 07 | stub |
| `POST /placement` | 08 | stub |
| `POST /generations` | 11 | done — save one generation |
| `GET /generations` | 11/12 | done — every row, feeds the map |
| `GET /generations/{id}` | 11 | done |
| `GET /history?address=` | 11 | done — that address's sequence, oldest first |
| `PATCH /generations/{id}/correction` | 09 | done |
| `POST /propagate` | 10 | done |
| `GET /propagate/radii` | 10 | done — `[50, 100, 250]` |

### POST /api/generations — what steps 05-08 should send

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

- `placement` accepts **extra fields** and stores them verbatim — add
  `footprintIoU`, `collisionFlag`, whatever step 08 produces, and nothing is
  dropped.
- `confidence_state` is optional; it defaults to `placement.confidence`.
- Unknown **top-level** fields are rejected with 422 on purpose, so a typo
  fails loudly instead of silently vanishing.
- `position` is `[lat, lng, z]`. The map converts to deck.gl's `[lng, lat, z]`.
  Step 02's footprint geometry is the other way round — `[lng, lat]` GeoJSON
  order. `POST /propagate` accepts either.

---

## Decisions worth knowing

### Steps 01-02

**The spec's Overpass query misses real buildings.** `way["building"]` silently
returns nothing for any building mapped as a multipolygon relation — which at
VT includes **Torgersen Hall, Newman Library, Kelly Hall, Main Eggleston Hall,
East Eggleston Hall**. A way-only pull centred on Torgersen returned *Pearson
Hall West*, 40 m away, at high confidence: exactly the "building growing out of
the wrong footprint" failure the spec warns about. The query now asks for ways
*and* relations and stitches relation outer members into one ring.

**`footprintWidthMeters` / `footprintDepthMeters` are oriented to
`rotationDegrees`, not axis-aligned.** A raw lat/lng box around a building at
45° to the compass reports a near-square — for a real 80 × 40 m building it
gives 84.85 × 84.85, overstating the short axis by more than 2×. Step 08 fits
mesh scale to these numbers, so an axis-aligned box would corrupt every rotated
building.

**`selected` is `null` whenever the match is genuinely ambiguous.** Step 09 must
**never** fall back to `candidates[0]` — that is the auto-pick the spec forbids.
Every response carries a human-readable `reason`.

**One Overpass query serves both the match and the neighbours.** A single 250 m
query is partitioned: within 50 m become `candidates`, the rest `neighbors`.
Steps 08 and 10 read `neighbors` off the step 02 response rather than
re-querying Overpass.

**Backoff is deferred, not immediate**, and there are four mirrors, because both
spec'd Overpass endpoints were down simultaneously during the build. **Pre-cache
the demo buildings the night before — this is not hypothetical, it happened
twice.**

### Steps 09-12

**One row per generation, never one per address.** No upsert path, no unique
constraint on `address`. The history timeline in the click panel is the visible
proof — Burruss Hall shows `reclaimed → flooded → scorched`.

**Write failures are loud.** Every store method raises; nothing returns a falsy
sentinel. Handlers log `PERSISTENCE FAILURE` and return 502, and the frontend
client throws rather than resolving to `null`. A generation that looked saved
but never persisted would quietly break both history and Propagate.

**Propagate reveals, it does not generate.** Clicking Propagate during judging
queries pre-baked rows within the radius that share the source's World State.
Neighbours with no row come back as `pending` and are reported honestly
("4 revealed · 2 not pre-baked") rather than silently omitted.

**Esri satellite tiles** sit alongside the keyless OSM raster tiles for the
panel's satellite toggle. Also keyless, attribution included. OSM stays the
default — no MapTiler key anywhere.

---

## Two corrections to file 12, verified against running code

1. **`scenegraph: d => d.mesh_url` does not work in deck.gl 9.** That prop is
   typed `any` (URL / parsed glTF / Promise), *not* an `Accessor` the way
   `getOrientation` is. Passing a function makes the layer try to load the
   function itself as a model. Rows are grouped by `mesh_url` with one
   `ScenegraphLayer` per distinct mesh instead.
2. **`roll: 90` is correct and load-bearing.** Verified visually against a
   purpose-built asymmetric mesh: at `roll: 90` buildings stand upright, at
   `roll: 0` they lie flat. Holds as long as step 07 emits Y-up glTF; the left
   panel has a live axis-check slider if that changes. Meshes should also carry
   a `NORMAL` attribute or shading goes flat and the roof pitch disappears.

---

## Frontend toolchain gotchas found during the merge

Three things bit during integration and will bite anyone who changes these
versions. All three are commented at the site of the fix as well.

**1. `maplibre-gl` is pinned to v5, not v6.** On v6 the map silently never
loads: `map.getStyle()` returns no sources and no layers, `isStyleLoaded()`
stays false, no tile request is ever made, and **no error is emitted** — the
canvas just stays blank. Its ESM worker loads but never finishes parsing the
style. v5 works. `npm audit` flags v6-and-below over a DoS in the `image-size`
ICNS/JXL/HEIF parsers; that is reachable only by feeding the map hostile image
tiles, and ours come from two fixed sources. A blank map is the worse bug.

**2. `@vitejs/plugin-react` is deliberately not in `vite.config.ts`.** With
Vite 8 (rolldown) it emits `RefreshRuntime.getRefreshReg(...)`, but the runtime
Vite serves at `/@react-refresh` does not define it, so every component module
throws and the app renders blank. Installing the optional `oxc-transform-react`
peer does not help. Vite 8 transforms `.tsx` natively off `jsx: react-jsx` in
`tsconfig.app.json`, so JSX, TypeScript and production builds are unaffected —
the only loss is Fast Refresh, meaning an edit does a full reload instead of
preserving component state.

**3. MapLibre's stylesheet overrides the map container's positioning.**
`.maplibregl-map` sets `position: relative`, and its CSS is imported after
`index.css`, so an unqualified `.map-root { position: absolute }` loses the
cascade and the map collapses to **zero height** while still reporting full
width. The rule is qualified as `.app-shell .map-root` to win on specificity
rather than import order.

---

## Open items for the team

1. **The footprint cache is in-memory**, so it dies with the server. Now that
   step 11 has a store layer, the cleanest fix is a `footprint_cache` table
   behind the same `GenerationStore`-style interface, keyed by rounded lat/lng
   + radius. Not built yet — it touches step 02's module, so it needs Ajeet's
   sign-off first.
2. **Steps 03-08 own the middle of the pipeline.** Everything either side is
   done, so the first end-to-end run is gated on those five stubs.
3. **Pre-bake the demo buildings the night before judging** — both for Overpass
   (which went down twice during the build) and for the TripoSR queue.

---

## Demo data

`backend/seed/seed_demo.py --reset` writes: Burruss Hall with three World States
(the timeline), three pre-baked neighbours at 41 m / 90 m / 185 m, one
deliberately `auto-low` row (McBryde Hall) for the correction demo, and Lane
Stadium at 420 m to prove the radius filter excludes.
