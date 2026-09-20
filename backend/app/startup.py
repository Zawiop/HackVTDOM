"""Ensure the demo data exists at boot.

Render's free tier wipes local disk — the SQLite file and everything under
`outputs/` — on every cold start after an instance spins down from
inactivity. A judge loading the site right after that would otherwise see an
empty map.

Seeds from `assets/seed-world.json`, which is the one seed dataset — the same
file `POST /api/world/seed` loads, through the same function. Booting used to
run `seed/prebake_demo.py` and then `seed/seed_demo.py`, and those two overlap:
prebake writes Pamplin Hall with its real mesh, seed_demo writes Pamplin Hall
again with the grey placeholder. Since the map shows the newest row per
address and seed_demo ran second, a cold-started instance served Pamplin as a
placeholder box with its real mesh hidden underneath.

The single path also fixes two quieter problems. `save_generation` mints a new
id per call, so the old boot path duplicated its whole dataset if it ever ran
twice against a non-empty store; `restore_generations` keeps the ids in the
file and skips rows already present, so running it again is a no-op. And
seed_demo computed placements through Overpass at boot — a network call on the
startup path of a server whose whole reason for auto-seeding is that Overpass
might be down. Everything in the JSON is already-computed step-08 output
pointing at meshes committed to the repo.

`seed/prebake_demo.py` and `seed/seed_demo.py` are still the tools that
produced these artifacts, and still run by hand. They are no longer a second
dataset that boots alongside this one.
"""

import logging
from pathlib import Path

log = logging.getLogger("scorched.startup")

BACKEND_DIR = Path(__file__).resolve().parent.parent
FOOTPRINT_CACHE_SEED = BACKEND_DIR / "assets" / "samples" / "footprint_cache.seed.json"


async def ensure_demo_seeded() -> None:
    from .config import settings
    from .services import cache, worldio
    from .store import build_store

    # A fresh disk means a fresh (empty) footprint cache too. Preloading the
    # committed snapshot means a visitor who types one of the demo addresses
    # into the live entry pipeline gets an instant, Overpass-free answer —
    # independent of whether the world itself needed seeding below.
    if FOOTPRINT_CACHE_SEED.exists():
        cache.seed_from(FOOTPRINT_CACHE_SEED)

    store = build_store(settings)
    try:
        existing = store.list_generations()
    except Exception:
        log.exception("could not check for existing rows before auto-seeding; skipping")
        return

    if existing:
        log.info("store already has %d row(s) — skipping auto-seed", len(existing))
        return

    log.info("store is empty — auto-seeding from the committed demo world")
    try:
        rows = worldio.load_seed_world()
        # Rewritten onto this instance's PUBLIC_BASE_URL. The file stores every
        # URL base-relative so the same bytes work on localhost and on Render.
        written = store.restore_generations(worldio.absolutize(rows))
        log.info("auto-seeded %d/%d row(s) from %s", written, len(rows), worldio.SEED_WORLD.name)
    except Exception:
        # A seeding hiccup must never take the whole API down — real address
        # lookups still work against an empty map.
        log.exception("auto-seed failed; the app will start with an empty map")
