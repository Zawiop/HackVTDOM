"""Ensure the demo data exists at boot.

Render's free tier wipes local disk — the SQLite file, `outputs/`, and the
footprint cache — on every cold start after an instance spins down from
inactivity. A judge loading the site right after that would otherwise see an
empty map and, worse, a footprint lookup that depends on Overpass answering at
exactly the wrong moment (every public Overpass mirror has gone down at some
point during this project).

This runs the identical code path `seed/prebake_demo.py` and `seed/seed_demo.py`
run locally — it is not a separate "production" path, just called instead of
typed. It is guarded by the store already having rows, so it is a no-op on a
warm instance or a populated Supabase project, and it never overwrites or
duplicates anything.
"""

import argparse
import logging
import sys
from pathlib import Path

log = logging.getLogger("scorched.startup")

BACKEND_DIR = Path(__file__).resolve().parent.parent
FOOTPRINT_CACHE_SEED = BACKEND_DIR / "assets" / "samples" / "footprint_cache.seed.json"

# `seed/` is a sibling of `app/`, not a package under it. The seed scripts add
# this themselves when run as `python seed/foo.py`, but importing them as a
# module (as we do here) needs it done first.
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


async def ensure_demo_seeded() -> None:
    from .config import settings
    from .services import cache
    from .store import build_store

    store = build_store(settings)
    try:
        existing = store.list_generations()
    except Exception:
        log.exception("could not check for existing rows before auto-seeding; skipping")
        return

    if existing:
        log.info("store already has %d row(s) — skipping auto-seed", len(existing))
        return

    log.info("store is empty — auto-seeding the demo dataset")

    # A fresh disk means a fresh (empty) footprint cache too. Preloading the
    # committed snapshot means the demo buildings resolve from disk even if
    # Overpass happens to be down at the exact moment this instance wakes up.
    if FOOTPRINT_CACHE_SEED.exists():
        cache.seed_from(FOOTPRINT_CACHE_SEED)

    try:
        from seed import prebake_demo, seed_demo

        await prebake_demo.main_async(argparse.Namespace(live=False, reset=False))
        await seed_demo.run(reset=False)
    except Exception:
        # A seeding hiccup must never take the whole API down — real address
        # lookups still work against an empty map.
        log.exception("auto-seed failed; the app will start with an empty map")
