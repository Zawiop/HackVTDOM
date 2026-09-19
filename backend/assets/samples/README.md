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
