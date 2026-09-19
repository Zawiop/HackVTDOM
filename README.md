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

## Tech stack

Every external service below is free with no credit card — see `markdown_files/00-overview.md`
for why each one was chosen over the paid option it replaced.

- **Backend:** Python + FastAPI
- **Frontend:** React + Vite + TypeScript
- **Map + 3D placement:** MapLibre GL JS + deck.gl (`ScenegraphLayer`), free keyless OSM raster tiles
- **Geocoding:** Nominatim (OpenStreetMap)
- **Building footprints:** OpenStreetMap Overpass API
- **Street imagery:** Mapillary
- **AI image redesign:** Google Gemini image model
- **Image → 3D mesh:** TripoSR via Hugging Face Spaces
- **Database:** Supabase (Postgres)

## Repo layout

```
backend/          # FastAPI service — one router per pipeline step
  app/models/     # Pydantic models: the API contract everyone builds against
  app/routers/    # One module per route; stubs return 501 until their owner lands
  app/services/   # External API clients + geometry helpers
  app/store/      # Persistence: Supabase, or a local SQLite fallback
  sql/            # Postgres schema — run once in the Supabase SQL editor
  seed/           # Demo data + the placeholder building mesh
  tests/
frontend/         # React + Vite app
  src/types/      # TypeScript mirror of the backend contract
  src/map/        # MapLibre + deck.gl: the 3D building layer
markdown_files/   # Per-module build specs, numbered by pipeline step
STATUS.md         # Decisions, spec deviations, and open questions
```

## Getting started

```bash
cd backend && python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
.venv/bin/python -m uvicorn app.main:app --reload --port 8000
```

```bash
cd frontend && npm install && cp .env.example .env && npm run dev
```

Never commit a `.env`.

With `SUPABASE_URL` unset the backend uses a local SQLite file at
`backend/local.db` — same schema, same behaviour — so it runs before anyone has
touched Supabase. Load the demo buildings with:

```bash
cd backend && .venv/bin/python seed/seed_demo.py --reset
```

## Team

Built by our VTHacks 14 team. See `markdown_files/` for the module breakdown, and `STATUS.md`
for decisions made where the specs were silent.

Map data © OpenStreetMap contributors, licensed under the ODbL.
Satellite imagery © Esri, Maxar, Earthstar Geographics.
