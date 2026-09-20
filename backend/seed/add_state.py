"""Add a World State to buildings that are already on the map.

The pre-bake gives each neighbour a single state, which makes the map look
like a building can only ever be one thing. This runs the real pipeline —
image (05), mesh (06+07), placement (08), persistence (11) — for whichever
states you ask for, so a building ends up with a history worth stepping
through.

    ./.venv/bin/python seed/add_state.py --state reclaimed
    ./.venv/bin/python seed/add_state.py --state buried --address "Norris Hall"
    ./.venv/bin/python seed/add_state.py --spread      # a different state each

Every hosted image provider is currently out of quota, so this will fall
through to the local restyle (see app/generation/local_restyle.py). That is
reported per row rather than hidden — a row generated locally is marked as
such in its response, and the mesh built from it is still a real mesh.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

API = "http://127.0.0.1:8000"
PHOTO = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "burruss_hall.jpg"
STATES = ["reclaimed", "flooded", "scorched", "buried", "petrified"]


async def main_async(args) -> int:
    photo = PHOTO.read_bytes()
    async with httpx.AsyncClient(timeout=600) as c:
        rows = (await c.get(f"{API}/api/generations")).json()
        by_address: dict[str, list[dict]] = {}
        for r in rows:
            by_address.setdefault(r["address"], []).append(r)

        targets = [
            (addr, rs) for addr, rs in by_address.items()
            if not args.address or args.address.lower() in addr.lower()
        ]
        if not targets:
            print(f"no building matching {args.address!r}")
            return 1

        for i, (address, existing) in enumerate(sorted(targets)):
            have = {r["world_state"] for r in existing}
            want = args.state or (STATES[i % len(STATES)] if args.spread else None)
            if want is None:
                want = next((s for s in STATES if s not in have), None)
            name = address.split(",")[0]
            if want in have:
                print(f"  {name:<16} already has {want}")
                continue

            row = existing[0]
            fp = (await c.post(f"{API}/api/footprint",
                               json={"lat": row["lat"], "lng": row["lng"]})).json()
            sel = fp.get("selected")
            if not sel:
                print(f"  {name:<16} skipped — footprint is ambiguous ({fp['reason'][:40]})")
                continue

            img = (await c.post(f"{API}/api/generate-image",
                                files={"photo": ("p.jpg", photo, "image/jpeg")},
                                data={"worldState": want})).json()
            mesh = (await c.post(f"{API}/api/generate-mesh", json={
                "imageUrl": img["imageUrl"],
                "footprintWidthMeters": sel["footprintWidthMeters"],
                "footprintDepthMeters": sel["footprintDepthMeters"]})).json()
            pl = (await c.post(f"{API}/api/placement", json={
                "footprint": sel,
                "meshExtentsMeters": mesh["normalization"]["extentsMeters"],
                "neighbors": fp["neighbors"],
                "footprintConfidence": fp["confidence"]})).json()
            saved = await c.post(f"{API}/api/generations", json={
                "address": address, "lat": row["lat"], "lng": row["lng"],
                "source_photo": row.get("source_photo"), "artifact": img["imageUrl"],
                "mesh_url": mesh["meshUrl"], "world_state": want,
                "placement": {
                    "rotationDegrees": pl["rotationDegrees"], "scale": pl["scale"],
                    "scaleXYZ": pl.get("scaleXYZ"), "position": pl["position"],
                    "confidence": pl["confidence"],
                    "scoredRotationCandidates": pl["scoredRotationCandidates"],
                    "footprintWidthMeters": pl.get("footprintWidthMeters"),
                    "footprintDepthMeters": pl.get("footprintDepthMeters"),
                }})
            ok = saved.status_code == 201
            print(f"  {name:<16} + {want:<11} {'ok' if ok else 'FAILED ' + str(saved.status_code)}"
                  f"  image={img['provider']:<14} mesh={mesh['provider']:<6} {pl['confidence']}")

        total = len((await c.get(f"{API}/api/generations")).json())
        print(f"\ntotal rows: {total}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", choices=STATES, help="the state to add to every match")
    ap.add_argument("--address", help="only buildings whose address contains this")
    ap.add_argument("--spread", action="store_true",
                    help="give each building a different state instead of the same one")
    return asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
