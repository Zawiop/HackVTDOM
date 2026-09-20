# Deploying Scorched Nebraska

Backend on Render, frontend on Vercel. Both have free tiers and both need you
to sign up and connect GitHub — that part has to be you; nobody else can enter
your credentials for you. Everything else (the two config files, the CORS
wiring, making sure a cold start never shows an empty map) is already done —
see `render.yaml` and `frontend/vercel.json`.

Total time: about 10 minutes, in two passes (each side needs to know the
other's URL before it's fully configured).

## Before you start

Have these ready to paste in — you'll need them in step 2, and you enter them
directly into Render's dashboard, never anywhere else:

- A real contact email, for `NOMINATIM_USER_AGENT` (their policy requires one)
- Optionally: `GEMINI_API_KEY`, `HF_TOKEN`, `MAPILLARY_ACCESS_TOKEN`,
  `SUPABASE_URL` + `SUPABASE_SECRET_KEY` — all optional. Without them the site
  still works: image generation falls back to a local colour-grade
  (`local-restyle`, see `STATUS.md`), mesh generation falls back to a
  placeholder, and persistence falls back to a local SQLite file.
- If you *are* using Supabase: run `backend/sql/001_generations.sql` in the
  Supabase SQL editor before your first deploy.

## 1. Push to GitHub

Already done if you're reading this from the repo. Both Render and Vercel
deploy straight from your GitHub repo on every push to `main`.

## 2. Backend on Render

1. [render.com](https://render.com) → sign up → connect GitHub.
2. **New** → **Blueprint** → pick this repo. Render reads `render.yaml`
   automatically and shows you every env var it declares.
3. For each var with no value shown, paste yours in — or leave it blank to
   use the fallback behavior described above. Change `NOMINATIM_USER_AGENT`
   to a real email.
4. Deploy. Render assigns a URL immediately, of the form
   `https://scorched-nebraska-api.onrender.com` (or your own service name).
   **Copy this URL** — you need it in the next step.
5. First build takes a few minutes. Once it's up, `https://<your-url>/api/health`
   should return `{"status":"ok",...}`.

## 3. Frontend on Vercel

1. [vercel.com](https://vercel.com) → sign up → connect GitHub.
2. **Add New** → **Project** → import this repo.
3. **Root Directory: set it to `frontend`** — this is the one setting Vercel
   won't infer on its own for a repo laid out like this one. Everything else
   (`frontend/vercel.json`) is auto-detected from there.
4. Add an environment variable: `VITE_API_BASE_URL` = the Render URL from
   step 2 (no trailing slash).
5. Deploy. Vercel assigns a URL like `https://your-app.vercel.app`. **Copy it.**

`frontend/vercel.json` also contains `/api` and `/outputs` rewrites to the
temporary Cloudflare tunnel used by the current live demo. They keep that
deployment working when `VITE_API_BASE_URL` is unset. Once the Render URL is
configured, the frontend sends API requests directly to Render and generated
artifact URLs also come from Render, so the tunnel rewrites are no longer on
the production request path. They can then be removed after the Render-backed
deployment has been verified.

## 4. Close the loop

The backend needs to know the frontend's real URL (for CORS) and its own
(for the links it hands back in API responses) — neither was knowable until
step 3 finished.

1. Back in the Render dashboard → your service → **Environment**.
2. Set `PUBLIC_BASE_URL` to the exact Render URL from step 2.
3. Set `CORS_ORIGINS` to `["https://your-app.vercel.app"]` — the Vercel URL
   from step 3, **as a JSON array with brackets and quotes**. (This one field
   parses differently from the comma-separated ones like `MESH_PROVIDERS`;
   getting the format wrong silently breaks every request from the frontend.)
4. Save — Render restarts the service automatically, no manual redeploy needed.

## 5. Check it actually works

Open the Vercel URL. You should see the map with the pre-baked demo buildings
already on it — a fresh backend seeds itself automatically on first boot (see
"Why a cold start is never empty" below), so if the map is blank, check the
Render service logs for a `scorched.startup` line.

Try locating a real address (e.g. "Burruss Hall, Blacksburg, VA") to confirm
the frontend is actually reaching the backend and not just showing cached
seed data.

## Why a cold start is never empty

Render's free tier spins a service down after 15 minutes idle and wipes its
local disk on every cold start — the SQLite file, generated images/meshes,
and the footprint cache all reset to nothing. `app/startup.py` restores the
world committed at `backend/assets/seed-world.json` — the same file
`POST /api/world/seed` reads — every time the store comes up empty. Every URL
in it points at `backend/assets/samples/`, which is in the repo, so this is a
handful of database inserts with no network call at all: no Overpass, no AI
provider, nothing that can be down at the exact moment someone loads the site
after it's been asleep. It's a no-op once the store has rows, so it never
duplicates data or interferes with a real Supabase project.

`seed/prebake_demo.py --live` is the separate, manual tool for regenerating
that committed world against the real providers when someone wants fresher
demo content — it is deliberately not part of the boot path, so a cold start
can never call an AI provider or spend anyone's quota on its own.

Anything a real visitor generates live is not covered by this — it lives on
the same ephemeral disk and can be lost on the next cold start. That's a
known, accepted limit of the free tier; see `STATUS.md` for what upgrading
that would take (Supabase Storage for the generated files, matching what's
already done for the database rows).

## Costs

Both tiers used here are free. Render's free web service sleeps after 15 min
idle and takes ~30-60s to wake back up on the next request — normal for a
hackathon demo link, worth knowing if you're timing a live pitch around it. If
that cold-start delay is a problem during judging, load the URL yourself a
minute or two before you go on.
