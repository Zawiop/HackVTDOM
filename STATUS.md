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
