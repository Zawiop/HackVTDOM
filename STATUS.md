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
