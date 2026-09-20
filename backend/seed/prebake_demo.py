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
    ./.venv/bin/python seed/prebake_demo.py --force    # write even if already present

This is the *generator*. The dataset it produces is committed as
`assets/seed-world.json`, and that file is what actually seeds a world —
`POST /api/world/seed` loads it, and `app/startup.py` auto-seeds from it on a
cold start. So by default this skips any address already in the store rather
than writing a second copy of it: `save_generation` mints a fresh id per call,
and a duplicate row at the same coordinate hides the original behind it on the
map. `--force` writes anyway.

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

import httpx                                                      # noqa: E402

from app.config import settings                                  # noqa: E402
from app.generation import storage                               # noqa: E402
from app.models import GenerationCreate, Placement, ScoredRotation  # noqa: E402
from app.services import footprint as footprint_service          # noqa: E402
from app.services import mapillary                               # noqa: E402
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
    # The neighbourhood, all in the same World State so step 10's Propagate has something
    # real to reveal at each radius: Norris/Pamplin/Hancock inside 100 m, the rest inside
    # 250 m. Each one's image is its own real Mapillary photo (captured by a --live run
    # of this script), and its mesh is fitted to *that building's* own OSM footprint — six
    # distinct buildings, not one photo standing in for all of them.
    {
        "address": "Hitt Hall, Blacksburg, VA",
        "lat": 37.22945,
        "lng": -80.42606,
        "world_state": "flooded",
        "image": SAMPLES / "hitt_flooded.png",
        "mesh": SAMPLES / "hitt_flooded.glb",
        "mesh_response": SAMPLES / "hitt_flooded.mesh-response.json",
    },
    {
        "address": "Norris Hall, Blacksburg, VA",
        "lat": 37.22974,
        "lng": -80.42315,
        "world_state": "flooded",
        "image": SAMPLES / "norris_flooded.png",
        "mesh": SAMPLES / "norris_flooded.glb",
        "mesh_response": SAMPLES / "norris_flooded.mesh-response.json",
    },
    {
        "address": "Pamplin Hall, Blacksburg, VA",
        "lat": 37.22866,
        "lng": -80.42467,
        "world_state": "flooded",
        "image": SAMPLES / "pamplin_flooded.png",
        "mesh": SAMPLES / "pamplin_flooded.glb",
        "mesh_response": SAMPLES / "pamplin_flooded.mesh-response.json",
    },
    {
        "address": "Hancock Hall, Blacksburg, VA",
        "lat": 37.23026,
        "lng": -80.42426,
        "world_state": "flooded",
        "image": SAMPLES / "hancock_flooded.png",
        "mesh": SAMPLES / "hancock_flooded.glb",
        "mesh_response": SAMPLES / "hancock_flooded.mesh-response.json",
    },
    {
        "address": "Derring Hall, Blacksburg, VA",
        "lat": 37.22907,
        "lng": -80.4256,
        "world_state": "flooded",
        "image": SAMPLES / "derring_flooded.png",
        "mesh": SAMPLES / "derring_flooded.glb",
        "mesh_response": SAMPLES / "derring_flooded.mesh-response.json",
    },
    {
        "address": "Holden Hall, Blacksburg, VA",
        "lat": 37.23019,
        "lng": -80.42238,
        "world_state": "flooded",
        "image": SAMPLES / "holden_flooded.png",
        "mesh": SAMPLES / "holden_flooded.glb",
        "mesh_response": SAMPLES / "holden_flooded.mesh-response.json",
    },
]


def publish(path: Path, kind: str) -> str:
    """Copy a captured artifact into outputs/ and return the URL it is served at."""
    _, url = storage.save_bytes(path.read_bytes(), kind, path.suffix.lstrip("."))
    return url


def publish_bytes(data: bytes, kind: str, ext: str) -> str:
    _, url = storage.save_bytes(data, kind, ext)
    return url


async def find_real_photo(lat: float, lng: float) -> tuple[bytes, str] | None:
    """A real street-level photo of this exact building, if Mapillary has one.

    Six of the eight demo buildings previously reused Burruss's own photo as
    their generation input — different meshes, but the same wrong building
    texturing the "before" side of every one of them. This is why a --live
    prebake now looks for the real thing first, per building, before falling
    back to the shared photo.
    """
    result = await mapillary.fetch_mapillary_photos(
        lat, lng, settings.mapillary_access_token or None
    )
    photos = result.get("photos") or []
    if not photos:
        return None
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            r = await client.get(photos[0]["url"])
            r.raise_for_status()
            return r.content, "jpg"
    except Exception as exc:
        print(f"    could not download Mapillary photo ({str(exc)[:60]}) — using shared photo")
        return None


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

    source_photo_bytes = SOURCE_PHOTO.read_bytes()
    source_photo_url = None
    produced = None
    if live:
        real_photo = await find_real_photo(entry["lat"], entry["lng"])
        if real_photo:
            data, ext = real_photo
            source_photo_bytes = data
            source_photo_url = publish_bytes(data, "photos", ext)
            print(f"    real photo: {source_photo_url}")
        else:
            print("    no Mapillary coverage here — using the shared Burruss photo")
        produced = await generate_live(source_photo_bytes, entry["world_state"], fp.selected)

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
        source_photo=source_photo_url or publish(SOURCE_PHOTO, "photos"),
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
            # Carried so step 12 can draw at building scale: a fixed-radius flag
            # ring is invisible on a 130 m hall and swamps a 9 m outbuilding.
            footprintWidthMeters=fp.selected.footprintWidthMeters,
            footprintDepthMeters=fp.selected.footprintDepthMeters,
        ),
    )


async def main_async(args) -> int:
    if args.reset and settings.store_backend == "sqlite" and settings.sqlite_path.exists():
        settings.sqlite_path.unlink()
        print(f"removed {settings.sqlite_path}")

    store = build_store(settings)
    print(f"pre-baking into: {store.backend_name}"
          f"{' (live providers)' if args.live else ' (captured artifacts)'}\n")

    # What is already there, as (address, world state). These rows are the same
    # seven buildings `assets/seed-world.json` carries, so on an already-seeded
    # store every one of them would be a duplicate — and the map draws the
    # newest row per address, so the copy would hide the original.
    force = getattr(args, "force", False)
    present = set()
    if not force:
        present = {(r.address, r.world_state) for r in store.list_generations()}

    written = skipped = 0
    for entry in DEMOS:
        key = (entry["address"], entry["world_state"])
        if key in present:
            print(f"  skip  {entry['address'].split(',')[0]:<16} {entry['world_state']:<10}"
                  f" (already in the store — use --force to write anyway)")
            skipped += 1
            continue
        store.save_generation(await bake(entry, args.live))
        written += 1

    print(f"\npre-baked {written} row(s)"
          f"{f', skipped {skipped} already present' if skipped else ''}."
          f" total in store: {len(store.list_generations())}")
    print("Artifacts are served from outputs/ — the demo no longer needs any provider.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="call the real providers first")
    ap.add_argument("--reset", action="store_true", help="delete the local sqlite db first")
    ap.add_argument("--force", action="store_true",
                    help="write rows even if that address/state is already in the store")
    return asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
