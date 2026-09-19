"""Pre-bake the demo buildings so judging never waits on a live API.

Runs the real pipeline end to end for each demo entry — footprint (02), image (05),
mesh (06+07), placement (08), persistence (11) — and writes the artifacts into
`outputs/` so they are served from disk afterwards.

Both file 00 and file 06 are explicit that this must happen well before judging: the
public Overpass instance, the Gemini free tier and the Hugging Face Spaces have all
been unavailable at some point during this build, and none of them should be in the
critical path of a demo.

    ./.venv/bin/python seed/prebake_demo.py            # use the captured artifacts
    ./.venv/bin/python seed/prebake_demo.py --live     # regenerate through the providers
    ./.venv/bin/python seed/prebake_demo.py --reset    # clear the store first

Without --live the script uses the real generation outputs committed under
`assets/samples/` (see its README). They came out of the live pipeline unmodified, so
the resulting rows are genuine end-to-end output, just not generated on this run.
With --live it calls the providers and falls back to the captured artifact for any
step whose provider is unavailable, reporting which is which.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings                                  # noqa: E402
from app.generation import storage                               # noqa: E402
from app.models import GenerationCreate, Placement, ScoredRotation  # noqa: E402
from app.services import footprint as footprint_service          # noqa: E402
from app.services import placement as placement_service          # noqa: E402
from app.services import worldstate                              # noqa: E402
from app.store import build_store                                # noqa: E402

SAMPLES = Path(__file__).resolve().parent.parent / "assets" / "samples"
SOURCE_PHOTO = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "burruss_hall.jpg"

# Each entry is one row: a real building, a World State, and the captured artifacts
# for it. Add a building here and it is pre-baked with the rest.
DEMOS = [
    {
        "address": "Burruss Hall, Blacksburg, VA",
        "lat": 37.22906,
        "lng": -80.42372,
        "world_state": "scorched",
        "image": SAMPLES / "burruss_scorched.png",
        "mesh": SAMPLES / "burruss_scorched.glb",
        "mesh_response": SAMPLES / "burruss_scorched.mesh-response.json",
    },
    {
        "address": "Burruss Hall, Blacksburg, VA",
        "lat": 37.22906,
        "lng": -80.42372,
        "world_state": "flooded",
        "image": SAMPLES / "burruss_flooded.png",
        "mesh": SAMPLES / "burruss_flooded.glb",
        "mesh_response": SAMPLES / "burruss_flooded.mesh-response.json",
    },
]


def publish(path: Path, kind: str) -> str:
    """Copy a captured artifact into outputs/ and return the URL it is served at."""
    _, url = storage.save_bytes(path.read_bytes(), kind, path.suffix.lstrip("."))
    return url


async def generate_live(photo: bytes, world_state: str, footprint) -> tuple[str, str, dict] | None:
    """Try the real providers. Returns (image_url, mesh_url, extents) or None."""
    from app.generation.image_edit import generate_redesigned_image
    from app.generation.mesh_generate import generate_mesh

    prompt, _, _ = worldstate.resolve(world_state, None)
    try:
        image = await generate_redesigned_image(photo, prompt)
    # Deliberately NOT bare Exception: a TypeError here is a wrong call signature,
    # and swallowing it reports a provider outage that never happened.
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"    live image failed ({str(exc)[:70]}) — using captured artifact")
        return None

    image_bytes = storage.local_path_for_url(image["imageUrl"]).read_bytes()
    try:
        mesh = await generate_mesh(
            image_bytes,
            footprint_width_m=footprint.footprintWidthMeters,
            footprint_depth_m=footprint.footprintDepthMeters,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"    live mesh failed ({str(exc)[:70]}) — using captured artifact")
        return None

    if mesh.get("provider") == "placeholder":
        print("    live mesh fell through to the placeholder — using captured artifact")
        return None
    return image["imageUrl"], mesh["meshUrl"], mesh["normalization"]["extentsMeters"]


async def bake(entry: dict, live: bool) -> GenerationCreate:
    print(f"  {entry['address'].split(',')[0]} / {entry['world_state']}")

    fp = await footprint_service.lookup(entry["lat"], entry["lng"])
    if not fp.selected:
        raise SystemExit(f"    no footprint at {entry['lat']},{entry['lng']}: {fp.reason}")
    print(f"    footprint: {fp.selected.tags.get('name')} "
          f"{fp.selected.footprintWidthMeters} x {fp.selected.footprintDepthMeters} m")

    produced = None
    if live:
        produced = await generate_live(SOURCE_PHOTO.read_bytes(), entry["world_state"], fp.selected)

    if produced:
        image_url, mesh_url, extents = produced
        print(f"    generated live: {mesh_url}")
    else:
        image_url = publish(entry["image"], "images")
        mesh_url = publish(entry["mesh"], "meshes")
        extents = json.loads(entry["mesh_response"].read_text())["normalization"]["extentsMeters"]
        print(f"    cached artifact: {mesh_url}")

    computed = placement_service.compute_placement(
        polygon_lnglat=[(p[0], p[1]) for p in fp.selected.geometry],
        base_bearing_degrees=fp.selected.rotationDegrees,
        mesh_width_meters=extents["width"],
        mesh_depth_meters=extents["depth"],
        neighbors_lnglat=[
            [(p[0], p[1]) for p in n.geometry]
            for n in fp.candidates + fp.neighbors
            if n.osmId != fp.selected.osmId
        ],
        footprint_confidence=fp.confidence,
    )
    print(f"    placement: {computed['rotationDegrees']}deg, scale {computed['scale']}, "
          f"{computed['confidence']}")
    for name, check in computed["checks"].items():
        if not check["ok"]:
            print(f"      flagged {name}: {check['detail']}")

    return GenerationCreate(
        address=entry["address"],
        lat=entry["lat"],
        lng=entry["lng"],
        source_photo=publish(SOURCE_PHOTO, "photos"),
        artifact=image_url,
        mesh_url=mesh_url,
        world_state=entry["world_state"],
        placement=Placement(
            rotationDegrees=computed["rotationDegrees"],
            scale=computed["scale"],
            scaleXYZ=computed["scaleXYZ"],
            position=computed["position"],
            confidence=computed["confidence"],
            scoredRotationCandidates=[
                ScoredRotation(**c) for c in computed["scoredRotationCandidates"]
            ],
        ),
    )


async def main_async(args) -> int:
    if args.reset and settings.store_backend == "sqlite" and settings.sqlite_path.exists():
        settings.sqlite_path.unlink()
        print(f"removed {settings.sqlite_path}")

    store = build_store(settings)
    print(f"pre-baking into: {store.backend_name}"
          f"{' (live providers)' if args.live else ' (captured artifacts)'}\n")

    for entry in DEMOS:
        store.save_generation(await bake(entry, args.live))

    print(f"\npre-baked {len(DEMOS)} rows. total in store: {len(store.list_generations())}")
    print("Artifacts are served from outputs/ — the demo no longer needs any provider.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="call the real providers first")
    ap.add_argument("--reset", action="store_true", help="delete the local sqlite db first")
    return asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
