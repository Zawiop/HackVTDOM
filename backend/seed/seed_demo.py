"""Pre-bake extra supporting cast, by hand, on top of the committed seed world.

NOT the boot path. `assets/seed-world.json` is the one seed dataset — it is
what `POST /api/world/seed` loads and what `app/startup.py` auto-seeds on a
cold start, and it already carries Burruss plus six real neighbours with their
generated meshes. This script adds a few extra placeholder rows on top, for
cases that dataset does not cover: a building outside every propagate radius,
and a second low-confidence target. Addresses here must not overlap with it.

Pre-bake the supporting cast so Propagate is an instant reveal during judging.

Step 10 is explicit: do NOT generate neighbours live in front of judges. This
script writes the pre-baked neighbours and one deliberately low-confidence row so
the correction UI (step 09) has something real to fix.

Burruss itself — the hero building, with its real generated image, real mesh and
multi-state history — comes from `seed/prebake_demo.py`. Run that first:

    ./.venv/bin/python seed/prebake_demo.py --reset
    ./.venv/bin/python seed/seed_demo.py

Coordinates are the real geocoded positions of these buildings, because step 08
now matches each row against the actual OSM footprint at its coordinate — an
approximate fixture silently resolves to whichever building is really there.

One consequence to know before the pitch: VT buildings sit more than 100 m apart
centre-to-centre, so Propagate only reveals anything at the 250 m radius. The
50 m and 100 m tiers are honestly empty. Either demo at 250 m, or measure the
radius edge-to-edge instead of centroid-to-centroid (see STATUS.md).

Usage:  ./.venv/bin/python seed/seed_demo.py [--reset]
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings                     # noqa: E402
from app.services.geo import haversine_meters  # noqa: E402
from app.services import footprint as footprint_service       # noqa: E402
from app.services import placement as placement_service       # noqa: E402
from app.models import GenerationCreate, Placement, ScoredRotation  # noqa: E402
from app.store import build_store                    # noqa: E402

# Real coordinates, geocoded through step 01 (Nominatim) rather than guessed.
# Synthetic offsets used to sit on whichever building happened to be there, so a
# row labelled "Williams Hall" resolved to Patton Hall's footprint once step 08
# started matching against real OSM polygons.
BURRUSS = (37.22906, -80.42372)
MESH = "/placeholder.glb"  # served from frontend/public until real meshes exist
# frontend/public/placeholder.glb measures 10.0 x 6.6 m in its footprint plane
# (Y is up). Step 08 scales this to whatever the real footprint turns out to be.
MESH_WIDTH_M = 10.0
MESH_DEPTH_M = 6.6
# Distances from Burruss: Williams 141 m, McBryde 241 m.
#
# Every address here must be one that `assets/seed-world.json` does NOT carry.
# Pamplin Hall used to be first in this list, and the seed world has a Pamplin
# with its real generated mesh — so a machine that ran both ended up with two
# Pamplin rows, and because the map draws the newest row per address and this
# script ran second, the real mesh was hidden behind this grey placeholder.
# tests/test_world_io.py asserts the two sets stay disjoint.
NEIGHBOURS = [
    ("Williams Hall, Blacksburg, VA", 37.22788, -80.42430, 22.0, 0.9),
    ("Newman Library, Blacksburg, VA", 37.22881, -80.41945, 78.0, 1.25),
]
# Propagate spreads the *source row's* World State, so the supporting cast has to
# share it with the hero row prebake_demo.py writes — otherwise Propagate correctly
# reveals nothing and it looks broken.
HERO_WORLD_STATE = "scorched"
MCBRYDE = (37.23059, -80.42179)        # 241 m — inside the 250 m radius
MCBRYDE_ADDRESS = "McBryde Hall, Blacksburg, VA"
LANE_STADIUM = (37.21989, -80.41800)   # 1.1 km — outside every radius
LANE_STADIUM_ADDRESS = "Lane Stadium, Blacksburg, VA"
PHOTO = "https://upload.wikimedia.org/wikipedia/commons/thumb/2/2b/Burruss_Hall.jpg/640px-Burruss_Hall.jpg"


def addresses() -> set[str]:
    """Every address this script writes.

    Stated here so tests/test_world_io.py can assert it stays disjoint from
    `assets/seed-world.json` — the overlap this had with it once meant a real
    generated mesh was hidden behind a grey placeholder on the deployed map.
    """
    return {name for name, *_ in NEIGHBOURS} | {MCBRYDE_ADDRESS, LANE_STADIUM_ADDRESS}


def placement(lat, lng, rot=47.5, scale=1.0, confidence="auto-high"):
    return Placement(
        rotationDegrees=rot,
        scale=scale,
        position=[lat, lng, 0.0],
        confidence=confidence,
        scoredRotationCandidates=[
            ScoredRotation(rotationDegrees=rot, iou=0.81),
            ScoredRotation(rotationDegrees=(rot + 90) % 360, iou=0.44),
            ScoredRotation(rotationDegrees=(rot + 180) % 360, iou=0.78),
            ScoredRotation(rotationDegrees=(rot + 270) % 360, iou=0.41),
        ],
    )


async def real_placement(lat, lng, confidence=None):
    """Run step 08 against the building actually at this coordinate.

    Returns None when Overpass is unreachable, so seeding still works offline —
    the caller falls back to its hardcoded transform.

    Async, and does not call asyncio.run() itself: this is also invoked from
    app.startup's auto-seed, which already runs inside FastAPI's event loop —
    asyncio.run() cannot be nested inside one that is already running.
    """
    try:
        fp = await footprint_service.lookup(lat, lng)
    except footprint_service.FootprintUnavailable as exc:
        print(f"    (overpass unavailable: {exc!s:.60} — using fallback transform)")
        return None
    if not fp.selected:
        print(f"    (no footprint at {lat:.5f},{lng:.5f}: {fp.reason} — using fallback)")
        return None

    computed = placement_service.compute_placement(
        polygon_lnglat=[(p[0], p[1]) for p in fp.selected.geometry],
        base_bearing_degrees=fp.selected.rotationDegrees,
        mesh_width_meters=MESH_WIDTH_M,
        mesh_depth_meters=MESH_DEPTH_M,
        neighbors_lnglat=[
            [(p[0], p[1]) for p in n.geometry]
            for n in fp.candidates + fp.neighbors
            if n.osmId != fp.selected.osmId
        ],
        footprint_confidence=fp.confidence,
    )
    return Placement(
        rotationDegrees=computed["rotationDegrees"],
        scale=computed["scale"],
        scaleXYZ=computed["scaleXYZ"],
        position=computed["position"],
        confidence=confidence or computed["confidence"],
        scoredRotationCandidates=[
            ScoredRotation(**c) for c in computed["scoredRotationCandidates"]
        ],
    )


def row(address, lat, lng, world_state, *, rot=47.5, scale=1.0,
        confidence="auto-high", placement_override=None):
    return GenerationCreate(
        address=address, lat=lat, lng=lng,
        source_photo=PHOTO,
        artifact=PHOTO,
        mesh_url=MESH,
        world_state=world_state,
        placement=placement_override or placement(lat, lng, rot, scale, confidence),
    )


async def run(reset: bool = False) -> int:
    """The actual seeding logic, callable directly — no argv, no asyncio.run().

    Split out so app.startup can await this at server boot without going
    through argparse (which would try to parse uvicorn's own command-line
    arguments and crash) or asyncio.run() (which cannot nest inside the event
    loop FastAPI is already running).
    """
    if reset and settings.store_backend == "sqlite" and settings.sqlite_path.exists():
        settings.sqlite_path.unlink()
        print(f"removed {settings.sqlite_path}")

    store = build_store(settings)
    print(f"seeding into: {store.backend_name}")

    # Burruss itself is the hero building and belongs to prebake_demo.py, which
    # gives it the real generated image and mesh. Seeding a placeholder copy at the
    # same coordinate would bury those under a 100 m grey box.

    # --- pre-baked neighbours at real distances (step 10 reveal) ---
    for name, lat, lng, rot, scale in NEIGHBOURS:
        computed = await real_placement(lat, lng)
        g = store.save_generation(
            row(name, lat, lng, HERO_WORLD_STATE, rot=rot, scale=scale, placement_override=computed))
        d = haversine_meters(*BURRUSS, lat, lng)
        fit = f"  [{computed.rotationDegrees}deg, scale {computed.scale}]" if computed else ""
        print(f"  neighbour {name.split(',')[0]:<16} {d:6.1f}m  {g.confidence_state}{fit}")

    # --- one deliberately low-confidence row: warning ring + correction UI ---
    lat, lng = MCBRYDE
    # Forced auto-low whatever step 08 thinks — this row exists to demo step 09.
    low = store.save_generation(
        row(MCBRYDE_ADDRESS, lat, lng, HERO_WORLD_STATE,
            rot=15.0, scale=0.55, confidence="auto-low",
            placement_override=await real_placement(lat, lng, confidence="auto-low"))
    )
    print(f"  low-confidence  McBryde Hall     {haversine_meters(*BURRUSS, lat, lng):6.1f}m  "
          f"{low.confidence_state}  <- correction UI target")

    # --- outside every radius: proves the radius filter actually filters ---
    lat, lng = LANE_STADIUM
    store.save_generation(row(LANE_STADIUM_ADDRESS, lat, lng, HERO_WORLD_STATE,
                              rot=0.0, placement_override=await real_placement(lat, lng)))
    print(f"  far building    Lane Stadium     {haversine_meters(*BURRUSS, lat, lng):6.1f}m"
          f"  (outside 250m)")

    rows = store.list_generations()
    hero = next((r for r in rows if r.address.startswith("Burruss")), None)
    print(f"\nseeded {len(rows)} rows total.")
    if hero:
        print(f"source id for Propagate: {hero.id}")
    else:
        print("No Burruss row yet — run seed/prebake_demo.py for the hero building.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="delete the local sqlite db first")
    args = ap.parse_args()
    return asyncio.run(run(reset=args.reset))


if __name__ == "__main__":
    raise SystemExit(main())
