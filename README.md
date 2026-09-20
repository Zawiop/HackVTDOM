# HackVTDOM

Built for **VTHacks 14**, targeting the **Procedura AI** sponsor track.

## What it does

Turn a real building into its "Scorched Nebraska" post-apocalyptic version, then place it back on a live map at its exact real-world location, correctly scaled and rotated to match its real footprint.

1. Enter a building's address and upload a photo of it
2. Describe the transformation (overgrown, collapsed, abandoned, etc.)
3. An AI model generates the redesigned building image
4. The image is converted into a 3D mesh
5. The mesh is geocoded, matched to the real building footprint, and placed on the map with correct position, scale, and rotation
6. Every generated building persists on a shared map, growing into a collective "Scorched Nebraska" of campus

## Deploying it

See [DEPLOY.md](DEPLOY.md) — Vercel (frontend) + Render (backend), both free,
about 10 minutes. `render.yaml` and `frontend/vercel.json` are already set up;
a fresh deploy auto-seeds itself with the demo buildings on first boot.

## Tech stack

Every external service below is free with no credit card — see `markdown_files/00-overview.md`
for why each one was chosen over the paid option it replaced.

- **Backend:** Python + FastAPI
- **Frontend:** React + Vite + TypeScript
- **Map + 3D placement:** MapLibre GL JS + deck.gl (`ScenegraphLayer`), free keyless OSM raster tiles
- **Geocoding:** Nominatim (OpenStreetMap)
- **Building footprints:** OpenStreetMap Overpass API
- **Street imagery:** Mapillary
- **AI image redesign:** Google Gemini image model, falling through to FLUX.1 Kontext [dev] on a
  Hugging Face Space (our key has no free Gemini image quota; see `STATUS.md`)
- **Image → 3D mesh:** Stable Fast 3D on a Hugging Face Space (the TripoSR Space is down), then
  normalized with `trimesh`
- **Database:** Supabase (Postgres)

## Repo layout

```
backend/          # FastAPI service — one router per pipeline step
  app/models/     # Pydantic models: the API contract everyone builds against
  app/services/   # External API clients + geometry helpers
  tests/
frontend/         # React + Vite app
  src/types/      # TypeScript mirror of the backend contract
markdown_files/   # Per-module build specs, numbered by pipeline step
STATUS.md         # Decisions, spec deviations, and open questions
```

## Getting started

**Python 3.12 or newer is required** — the code uses PEP 604 unions and the
numpy/scipy pins need 3.11+. On macOS the system `python3` is 3.9 and will fail
at install; use `python3.12` explicitly (`brew install python@3.12`).

```bash
cd backend
python3.12 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
.venv/bin/python -m uvicorn app.main:app --reload --port 8000
```

```bash
cd frontend && npm install && cp .env.example .env && npm run dev
```

Then load the demo data, in this order — prebake owns the hero building and its
real generated artifacts, seed owns the supporting cast. A fresh clone with no
seed shows an empty map:

```bash
cd backend
./.venv/bin/python seed/prebake_demo.py --reset
./.venv/bin/python seed/seed_demo.py
```

Tests:

```bash
cd backend && ./.venv/bin/python -m pytest -q     # add -m live for the provider tests
cd frontend && npm test && npx tsc -b
```

Never commit a `.env`.

## Team

Built by our VTHacks 14 team. The pipeline is specified as fourteen numbered
modules in `markdown_files/`; each of us owned a contiguous slice of it.

| Who | Contact | Modules | What that covers |
| --- | --- | --- | --- |
| **Ajeet Bondugula** | ajeetbondugula@gmail.com | 01, 02 | Project skeleton and the entry pipeline: address geocoding, and the OSM footprint match with its ambiguity handling, mirror fallback and cache |
| **Aditya Jupally** (`autobot433`) | adityajupally@gmail.com | 03, 04, 08 | Photo input including the Mapillary street-level layer, the World State prompt set, and the placement transform |
| **Arrush Shah** | shaharrush@gmail.com | 05, 06, 07 | AI image editing, image-to-3D mesh generation, and mesh normalization |
| **Rishik Uppalapati** | rishik.uppalapati@gmail.com | 09, 10, 11, 12 | Correction UI, World Propagate, Supabase persistence, and the MapLibre + deck.gl 3D map |

Modules 04, 08 and 13 were landed on `main` ahead of Aditya's push while his
branch was still open; he merged around them, kept the versions already in place
rather than forcing a conflict on the geometry core, and contributed step 03's
Mapillary layer — the last unimplemented route in the project — on top. His
branch also verified the Mapillary API live and documented that it returns
non-deterministic result counts for identical queries, which is why that lookup
retries before reporting no coverage.

See `markdown_files/` for the module breakdown, and `STATUS.md`
for decisions made where the specs were silent.

Map data © OpenStreetMap contributors, licensed under the ODbL.
