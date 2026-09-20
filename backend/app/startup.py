"""Ensure the demo data exists at boot.

Render's free tier wipes local disk — the SQLite file and everything under
`outputs/` — on every cold start after an instance spins down from
inactivity. A judge loading the site right after that would otherwise see an
empty map.

This calls the exact same path `POST /api/world/seed` does: read the world
committed at `assets/seed-world.json`, insert its rows verbatim. No network
call, no Overpass, no provider — every URL in that file points at
`assets/samples/`, which is in the repo, so this works even with every
external dependency this project has offline at once. It is guarded by the
store already having rows, so it is a no-op on a warm instance or a
populated Supabase project, and it never overwrites or duplicates anything.

`seed/prebake_demo.py --live` is the separate, deliberately-manual tool for
*regenerating* `assets/seed-world.json` and its referenced files against the
real providers when someone wants fresher demo content — it is not part of
this boot path, so a stray automatic run can never call an AI provider or
spend anyone's quota.
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

    log.info("store is empty — auto-seeding the committed demo world")
    try:
        rows = worldio.load_seed_world()
        restored = store.restore_generations(worldio.absolutize(rows))
        log.info("auto-seed restored %d/%d row(s)", restored, len(rows))
    except Exception:
        # A seeding hiccup must never take the whole API down — real address
        # lookups still work against an empty map.
        log.exception("auto-seed failed; the app will start with an empty map")
