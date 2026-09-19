# Real generation outputs to build against (steps 05-07)

Real outputs from the live pipeline (2026-09-19), committed so steps 08-12 can be built and tested
without calling the HF Spaces. Everything here came out of `/api/generate-image` and
`/api/generate-mesh` unmodified. Input photo: `backend/tests/fixtures/burruss_hall.jpg`.

| File | What it is |
| --- | --- |
| `burruss_scorched.png` | `/api/generate-image` output, "scorched" prompt (FLUX.1 Kontext, 1264x816) |
| `burruss_flooded.png` | `/api/generate-image` output, "flooded" prompt |
| `burruss_scorched.glb`, `burruss_flooded.glb` | `/api/generate-mesh` output (SF3D + normalization), fitted to the real footprint below |
| `*.mesh-response.json` | The exact JSON `/api/generate-mesh` returned for each (URLs point at localhost:8000) |
| `burruss_footprint.json` | `POST /api/footprint {lat: 37.2288, lng: -80.4236}` → Burruss Hall, OSM relation 1074686, 101.88 x 70.79 m, bearing 137.07 |

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

Sample extents after normalization (from the response JSON):

| Mesh | width (X) | depth (Z) | height (Y) |
| --- | --- | --- | --- |
| scorched | 101.88 | 37.57 | 56.34 |
| flooded | 101.88 | 41.66 | 40.51 |

Depth is the least reliable number: it's inferred from a single street-level photo.

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
