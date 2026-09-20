# Real generation outputs to build against (steps 05-07)

Real outputs from the live pipeline, committed so steps 08-12 can be built, tested, and demoed
without calling any external provider. Everything here came out of `/api/generate-image` and
`/api/generate-mesh` unmodified.

**Recaptured 2026-09-20** with a working `HF_TOKEN`: every building below now has its **own**
real street-level photo (fetched live from Mapillary at its own coordinates by
`seed/prebake_demo.py --live`), not a shared stand-in. The first capture (2026-09-19) used
`tests/fixtures/burruss_hall.jpg` for all eight entries, including the six non-Burruss halls —
functionally fine for exercising steps 08-12, but it meant six different building meshes were all
textured from a photo of a seventh building. That is fixed now: run
`seed/prebake_demo.py --live --reset` again any time to recapture against whatever the providers
return that day; without `--live` it always falls back to these committed files.

| File | What it is |
| --- | --- |
| `burruss_scorched.png`, `burruss_flooded.png` | `/api/generate-image` output (FLUX.1 Kontext), Burruss Hall's own photo |
| `hitt_`, `norris_`, `pamplin_`, `hancock_`, `derring_`, `holden_flooded.png` | Same, each from that hall's own real Mapillary photo — six distinct buildings, six distinct source images |
| `*.glb` | `/api/generate-mesh` output (SF3D + normalization) for the matching image, fitted to that building's own real OSM footprint |
| `*.mesh-response.json` | `provider`, `confidence` and `normalization.extentsMeters` for the matching mesh (URLs point at localhost:8000) |
| `burruss_footprint.json` | `POST /api/footprint {lat: 37.2288, lng: -80.4236}` → Burruss Hall, OSM relation 1074686, 101.88 x 70.79 m, bearing 137.07 |
| `footprint_cache.seed.json` | A snapshot of the step 02 footprint cache for all demo coordinates, preloaded at boot (`app/startup.py`) so a fresh host never depends on Overpass answering at the wrong moment |

Two of the eight are genuinely `auto-low`, not planted: **Pamplin** is near-square, so its two
orientations score equally and step 08 correctly refuses to guess; **Holden**'s mesh only reaches
63% of its achievable IoU fit. Both are exactly what step 09's correction UI exists to fix.

### Two of these were refit (2026-09-20)

`holden_flooded.glb` and `derring_flooded.glb` came out of the generator as near-boxes with
**blank texture atlases** — flat white panels where the others carry windows and cornices — so
they rendered as featureless grey slabs on the map. Both were replaced by `norris_flooded.glb`
uniformly scaled and normalized onto their own hall's footprint, which is the same technique
that produced most of this set in the first place (one generated building, refit to each hall's
real OSM outline). Their `.mesh-response.json` carries a `note` saying so, and the two rows in
`backend/assets/seed-world.json` dropped the per-axis `scaleXYZ` that step 08 had computed to
compensate for the old meshes' proportions.

## Mesh convention (every mesh the backend returns)

- glTF 2.0 axes: **+Y up**, the **photographed facade faces +Z**, +X is the viewer's right when
  facing the facade (not mirrored).
- **Meters**, already sized so the longest horizontal side = the longest footprint side
  (`footprintWidthMeters`/`DepthMeters` passed in). Step 08's uniform scale should come out ≈ 1.
- **Pivot at base-center**: X/Z bounding-box center, lowest point at y = 0. Place it at the
  footprint centroid with z = 0; nothing floats or sinks.
- Walls are **squared to the X/Z axes** (photos are taken at an angle; normalization rotates the
  mesh's minimum-area ground rectangle onto the axes), so step 08's 0/90/180/270 candidates line
  up with real walls.
- Carries `POSITION`, `NORMAL`, `TEXCOORD_0` + a baseColor texture.

In deck.gl (`ScenegraphLayer`, one layer per mesh URL): `getOrientation: [0, yaw, 90]`.
Verified in a real deck.gl 9 + MapLibre render: upright, textured, grounded. At `yaw = 0` the facade faces
**south**; in general the facade's compass bearing is `180 - yaw` (yaw rotates counter-clockwise
seen from above). Mesh X (the facade's length) points east at yaw 0.

Extents after normalization (width/depth/height in meters — see each `*.mesh-response.json` for
the exact numbers). Depth is the least reliable of the three: it's inferred from a single
street-level photo, which is exactly why step 08's scale fit tolerates a shortfall there before
flagging anything (see `app/services/placement.py`).

## Entrances

Each `.glb` also carries its **entrances**: doors found in the image (OWLv2) and projected onto
the mesh, baked in as a glowing portal (an unlit amber frame + panel, a little proud of the
facade) and reported in the response as data:

```json
"entrances": [{
  "id": 0, "isMain": true,
  "position": [-12.261, 7.87, 16.793],   // bottom-center of the doorway, on the portal face
  "facing": [-0.1185, 0.0, 0.993],       // unit [x, 0, z]: outward, the way a player walks in
  "widthMeters": 6.83, "heightMeters": 8.29,
  "score": 0.43, "imageBox": [406, 532, 481, 623],
  "source": "detected", "confidence": "auto-high"
}]
```

Same frame as the mesh (meters, +Y up, facade +Z, y = 0 ground), so entrances follow the mesh
through step 08's placement: rotate `position`/`facing` by the placement yaw, scale `position`
by the placement scale, then offset to the building's lat/lng. `position[1] > 0` means the door
sits above the mesh's lowest point (Burruss's entrance is up a flight of steps) — it is not
floating. Every building has at least one: if no door is detected, a `source: "default"`
entrance goes at the facade's front-center flagged `auto-low`.

The portal geometry is separate from the building geometry inside the `.glb` (node names
`entrance_<id>_frame` / `_glow`), so it can be filtered out if you ever need the bare building —
`normalization.extentsMeters` already measures the building alone.
