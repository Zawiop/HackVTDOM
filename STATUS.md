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
