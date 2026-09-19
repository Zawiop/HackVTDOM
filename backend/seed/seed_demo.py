"""Pre-bake demo rows so Propagate is an instant reveal during judging.

Step 10 is explicit: do NOT generate neighbours live in front of judges. This
script writes the source building, its pre-baked neighbours, a multi-state
history for the timeline, and one deliberately low-confidence row so the
correction UI (step 09) has something real to fix.

Coordinates are approximate Virginia Tech drillfield positions used only as
demo fixtures — at runtime real coordinates come from steps 01/02.

Usage:  ./.venv/bin/python seed/seed_demo.py [--reset]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings                     # noqa: E402
from app.services.geo import haversine_meters, offset_meters  # noqa: E402
from app.models import GenerationCreate, Placement, ScoredRotation  # noqa: E402
from app.store import build_store                    # noqa: E402

BURRUSS = (37.22870, -80.42290)
MESH = "/placeholder.glb"  # served from frontend/public until real meshes exist
PHOTO = "https://upload.wikimedia.org/wikipedia/commons/thumb/2/2b/Burruss_Hall.jpg/640px-Burruss_Hall.jpg"


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


def row(address, lat, lng, world_state, *, rot=47.5, scale=1.0, confidence="auto-high"):
    return GenerationCreate(
        address=address, lat=lat, lng=lng,
        source_photo=PHOTO,
        artifact=PHOTO,
        mesh_url=MESH,
        world_state=world_state,
        placement=placement(lat, lng, rot, scale, confidence),
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="delete the local sqlite db first")
    args = ap.parse_args()

    if args.reset and settings.store_backend == "sqlite" and settings.sqlite_path.exists():
        settings.sqlite_path.unlink()
        print(f"removed {settings.sqlite_path}")

    store = build_store(settings)
    print(f"seeding into: {store.backend_name}")

    # --- source building, plus its history sequence (step 11 timeline) ---
    src = store.save_generation(row("Burruss Hall, Blacksburg, VA", *BURRUSS, "reclaimed"))
    store.save_generation(row("Burruss Hall, Blacksburg, VA", *BURRUSS, "flooded", rot=47.5))
    store.save_generation(row("Burruss Hall, Blacksburg, VA", *BURRUSS, "scorched", rot=47.5))
    print(f"  source {src.id} + 2 more states (history = 3)")

    # --- pre-baked neighbours at known distances (step 10 reveal) ---
    neighbours = [
        ("Williams Hall, Blacksburg, VA", 40, 10, 22.0, 0.9),
        ("Pamplin Hall, Blacksburg, VA", 85, -30, 112.0, 1.1),
        ("Newman Library, Blacksburg, VA", 175, 60, 78.0, 1.25),
    ]
    for name, north, east, rot, scale in neighbours:
        lat, lng = offset_meters(*BURRUSS, north, east)
        g = store.save_generation(row(name, lat, lng, "reclaimed", rot=rot, scale=scale))
        d = haversine_meters(*BURRUSS, lat, lng)
        print(f"  neighbour {name.split(',')[0]:<16} {d:6.1f}m  {g.confidence_state}")

    # --- one deliberately low-confidence row: warning ring + correction UI ---
    lat, lng = offset_meters(*BURRUSS, 120, 95)
    low = store.save_generation(
        row("McBryde Hall, Blacksburg, VA", lat, lng, "reclaimed",
            rot=15.0, scale=0.55, confidence="auto-low")
    )
    print(f"  low-confidence  McBryde Hall     {haversine_meters(*BURRUSS, lat, lng):6.1f}m  "
          f"{low.confidence_state}  <- correction UI target")

    # --- outside every radius: proves the radius filter actually filters ---
    lat, lng = offset_meters(*BURRUSS, 420, 0)
    store.save_generation(row("Lane Stadium, Blacksburg, VA", lat, lng, "reclaimed", rot=0.0))
    print(f"  far building    Lane Stadium     {haversine_meters(*BURRUSS, lat, lng):6.1f}m"
          f"  (outside 250m)")

    total = len(store.list_generations())
    print(f"\nseeded. total rows: {total}")
    print(f"source id for Propagate: {src.id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
