# Scorched Nebraska

Built for **VTHacks 14**, targeting the **Procedura AI** sponsor track.

## What it does

Turn a real building into its "Scorched Nebraska" post-apocalyptic version, then place it back on a
live map at its exact real-world location, correctly scaled and rotated to match its real footprint.

1. Enter a building's address, and supply one or more photographs of it — uploaded, or picked from
   nearby street-level imagery when there's coverage
2. Choose a World State, or describe the transformation in your own words
3. An AI model generates the redesigned building image
4. The image is converted into a 3D mesh
5. The mesh is normalized, matched to the real OSM building footprint, and placed on the map with
   correct position, scale and rotation
6. Every generation persists as its own row, so one address accumulates a sequence of world states
   and the shared map grows into a collective "Scorched Nebraska" of campus

## Tech stack

Every external service below is free with **no credit card anywhere** — that constraint is what
drove several of the choices, and `markdown_files/00-overview.md` records why each one changed.

| | |
|---|---|
| **Backend** | Node.js + Express (TypeScript) |
| **Frontend** | React + Vite (TypeScript) |
| **Map + 3D placement** | MapLibre GL JS + deck.gl (`ScenegraphLayer`), keyless OSM raster tiles |
| **Geocoding** | Nominatim — free, no key, but requires a real `User-Agent` |
| **Building footprints** | OpenStreetMap Overpass API |
| **Source photography** | Manual upload (required path) + Mapillary (convenience layer) |
| **AI image redesign** | Google Gemini image model ("Nano Banana") |
| **Image → 3D mesh** | `stabilityai/TripoSR` via its public Hugging Face Space |
| **Mesh normalization** | `trimesh` / Blender headless |
| **Database + storage** | Supabase (Postgres) |

Mesh generation and normalization (steps 06/07) are expected to use Python tooling — `gradio_client`
against the TripoSR Space, and `trimesh` for normalization — so the stack is TypeScript everywhere
except those two steps.

**Superseded, for anyone reading an older draft:** Mapbox GL JS and Mapbox Geocoding (→ MapLibre and
Nominatim), MapTiler (dropped entirely), Replicate / Flux Kontext (→ Gemini), and Meshy / Tripo3D
(→ TripoSR). Meshy's free plan is web-app-only; its API is pay-before-you-go, so it cannot be used
for free at all. Details in `markdown_files/00-overview.md`.

## Repo layout

```
backend/          # Express API (TypeScript)
  src/
    routes/       # one file per module, registered in src/app.ts
    services/     # the actual per-step logic
    geo/          # projection, polygon and mesh maths for the placement step
    types/        # the API contract everyone builds against
    config/       # env access, in one place
    lib/          # small HTTP helpers
  test/
    fixtures/     # real OSM footprints + real .glb files, checked in
  scripts/        # smoke check and the placement preview renderer
frontend/         # React + Vite app
markdown_files/   # per-module build specs, 00 through 13
STATUS.md         # module status, integration notes, known gaps
```

`markdown_files/00-overview.md` is the architecture contract — read it before the numbered specs.
There is no `packages/shared/` and no `docs/`; earlier drafts of this file referred to both.

## Getting started

```bash
cd backend && npm install && npm run dev      # http://localhost:8787
```

```bash
cd frontend && npm install && npm run dev     # http://localhost:5173, proxies /api to the backend
```

Copy `backend/.env.example` to `backend/.env` and fill in the keys you need. Every one is free to
obtain and none requires a card. **Never commit `.env`** — it is gitignored, and so is
`frontend/.env`.

### Checks

```bash
cd backend && npm run verify
```

Typecheck, tests, then a smoke script that runs the real pipeline under plain Node. That last step
is not redundant: Vitest runs through Vite, which resolves CommonJS dependencies differently from
Node, and that difference has already hidden one bug that broke `npm start` while every test passed.

```bash
cd backend && npm run preview
```

Renders each placed mesh outline over its real OSM footprint, for eyeballing the geometry.

## Module status

Per-module state, integration notes and open questions live in **`STATUS.md`**. Keep it current —
it is where cross-module findings go, including things one module discovers about another's service.

## Attribution

Required, and easy to forget until the day of judging. Both belong in the map UI:

- © OpenStreetMap contributors (ODbL — covers Nominatim geocoding and Overpass footprints)
- Imagery © Mapillary contributors

A note for the pitch: OSM is community-sourced, not an official cadastral dataset. It is the right
practical choice here, and saying so in one sentence beats letting a judge catch the gap unaddressed.
