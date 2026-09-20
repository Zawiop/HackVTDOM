# Footprint-driven Scorched Nebraska assets

## Architecture-preserving correction

For a complete original textured mesh, use the source-preserving path instead of
replacing the architecture with an extrusion:

```bash
cd backend
.venv-footprint/bin/python scripts/build_footprint_asset.py \
  --source-mesh /path/to/original-normalized-building.glb \
  --footprint assets/samples/burruss_footprint.json \
  --output /tmp/scorched-nebraska/scorched-preserved.glb
```

This keeps the source's vertices, topology, UVs and architectural parts. Supplying
`--footprint` fits width and depth, and uses the **width scale for height too** so
the facade and tower do not get squashed. OSM height is recorded as conflicting
metadata when it disagrees, rather than silently compressing the whole building.
Omit `--footprint` to keep the original scale and transforms exactly. Input must be
normalized +Y up, front +Z, with X corresponding to footprint width. The fit
enforces horizontal metric extents, not an arbitrary polygon silhouette. The
preserved source height is still an estimate, not a verified real-world height.
Only `--height` requests a different total height. An override changing facade
height/width by more than 20% fails unless `--allow-height-distortion` is also
explicitly supplied. Keep the source
orientation and use the fitted base-center anchor, scale 1. The source's existing
placement must be adjusted if its old pivot was not base-center.

The implementation is `preserve.py`, exported as `restyle_existing_asset`.
`../scorch_material.py` adds irregular neutral soot and ash to existing albedo
without changing alpha. Roof shapes, towers, windows and texture coordinates are
retained. Open or nonmanifold body meshes fail a welded topology check; entrance
overlay nodes are exempt. This is deliberately not a hole-filling algorithm: it
cannot reconstruct architecture already missing in the supplied mesh. Use an
intact source, not a previously demolished/generated version, for intact results.

The scorched preset now explicitly keeps roofs/floors/structure complete. The
local image fallback no longer applies an orange wash, and the untextured
multiview fallback uses neutral spatial soot variation instead of ochre. Existing
source colours are preserved. Image/mesh cache versions were bumped; regenerate
old results to apply these changes. Stored map assets are not replaced in place.

For footprint-only massing, underside caps are now enabled by default. Wall/roof
T-junctions are split without moving their surfaces, and serialized validation
checks that the welded solid is watertight. This closes the asset but does not
turn a single-height massing model into the original tower/roof architecture.

The earlier fitted Burruss example was incorrectly compressed from 56.34 m to
20.70 m while its depth was expanded from 37.57 m to 70.79 m. That retained faces
but distorted the architecture. The corrected source-mode default gives
101.88 m width, 70.79 m depth, and 56.34 m source-derived height with zero facade
aspect change. The height discrepancy remains explicitly unresolved. Reports now
include per-axis scales, facade aspect change, and the height policy. The preview
script renders all faces; its former triangle subsampling also created misleading
visual holes.

Architecture decision: edited image → optional existing RGBA cutout → perspective-rectified facade → exact OSM extrusion → procedural unseen surfaces → one PBR atlas → validated GLB. This CPU-only path replaces learned reconstruction **for callers of this module**; it does not silently switch the existing API/provider routes. There are no API calls, model downloads, GPU requirements, or service charges in this module.

This prioritizes footprint fidelity, flat bases and hard wall edges at map distances. It is a constant-height massing model: towers, pitched roofs, destroyed roof openings, recess geometry and overhangs are not reconstructed. Photo-derived normal cues do not restore those structures. The existing image transformation is outside the measured runtime; FLUX on 24 GB MPS plus these stages is not established to meet two minutes end to end.

## 1. Final pipeline

1. Read a ring or GeoJSON Polygon/MultiPolygon (including holes), with explicit CRS. Invalid rings fail rather than silently dropping parts. WGS84 coordinates are `[longitude, latitude]`, even for the `latlon` alias. Projected CRS coordinates are `[x, y]`; `meters`/`local` means east/north in meters.
2. Use pyproj local azimuthal equidistant coordinates. Rotate X along the supplied compass bearing and Z perpendicular. A missing bearing is derived from the longest exterior segment.
3. Enforce **both** supplied footprint dimensions in this frame. Scaling is about its bounding center. This deliberately changes coordinates when dimensions conflict, and records any correction over 2%. Dimensions mean along-bearing/perpendicular extents, not longitude/latitude AABB extents. Check a suspect bearing rather than using dimensions measured in another frame.
4. Height hierarchy: explicit `height_m` → parsable OSM `height` (meters or feet) → `building:levels × 3.2` → default `3 × 3.2 = 9.6 m`. Explicit and OSM heights must be 0.5–500 m; levels-derived height is clamped to 3.2–120 m. Invalid tags fall through with warnings. No uncalibrated photo-aspect or learned-mesh height estimate is trusted. `height` includes the whole constant-height extrusion; no extra roof height is added.
5. Associate the photo with an explicit normalized edge index, or choose an outward-facing unobstructed edge from building-to-camera bearing. Without either, select the longest edge and warn. A polygon and image alone cannot resolve this correspondence. A camera's viewing heading is generally the opposite of the required building-to-camera bearing.
6. Detect a facade quadrilateral using alpha/edge contours, then eave/base lines, then a bounded crop. Rectify with `cv2.getPerspectiveTransform` and `warpPerspective`. Four-point override uses EXIF-oriented pixels, TL/TR/BR/BL. Normal runs require no interaction; low-confidence automatic results must not be mistaken for semantic segmentation. Existing rembg RGBA output is accepted directly.
7. Apply bounded illumination flattening in linear light: low-frequency log-luminance gain, default strength 0.35, gain restricted to 0.8–1.25. Preserve high-frequency detail with gentle unsharp masking. Deep shadows and highlights are **not** recovered; set strength to zero to preserve intentional world-state lighting.
8. Triangulate roof and floor with earcut, preserving courtyards and concavity. Split wall/roof normals. Assign the photo to one selected edge; subdivide unseen walls into approximately 8 m UV patches using deterministic world-state masonry. Courtyard walls get the same material policy. Roof receives a separate low-frequency material island. Join T-junctions and retain the floor by default for a closed solid (`include_floor=False` explicitly opts out). No repeated photographs, invented windows, ground apron, smoothing or learned mesh repair.
9. Rotate the selected facade toward glTF +Z; +Y up, meters, base Y=0. Re-center the final horizontal AABB and compensate the geographic anchor. Emit one material with padded albedo/normal/metallic-roughness atlases. The roughness texture packs G=roughness, B=zero metallic, R=255 (not bound as AO). Albedo is JPEG; normal/roughness PNG. Mipmap minification sampler uses LINEAR_MIPMAP_LINEAR; the browser generates mip levels. Gutters reduce, but cannot eliminate, deep-mip atlas bleeding.
10. Start at 2048 and fall back to 1024, then 512 until under the requested byte budget. Fail if even 512 is too large. Geometry is already low-poly: intentionally do **not** pad a 390-triangle building to 10–20k triangles. Maximum is 30k. Choose `texture_size=1024` for ten unique simultaneous assets when texture memory matters. At 2048, three RGBA atlases plus mipmaps can consume about 64 MiB GPU memory per building despite small compressed GLB size; ten unique buildings can approach 640 MiB.

## 2–3. Dependencies and files

```
backend/requirements-footprint.txt
backend/app/generation/footprint_asset/
    __init__.py       # public import
    geometry.py       # CRS, dimensions, height, facade association, extrusion
    textures.py       # homography, delighting, procedural/PBR atlas
    pipeline.py       # builder, export, serialized validation, JSON CLI
    README.md
backend/scripts/build_footprint_asset.py  # existing footprint response adapter
backend/tests/test_footprint_asset.py     # offline regression tests
```

Dependencies: NumPy, SciPy (trimesh sparse vertex-normal calculations), trimesh, Pillow, Shapely, OpenCV headless, pyproj, mapbox-earcut. No PyTorch is needed; the M5 GPU stays available to the existing image editor.

## 4. Complete implementation

The sibling Python files and adapter contain the full executable implementation, with no omitted inference functions or pseudocode. `build_asset` returns a JSON-serializable report and writes `.glb`, `.report.json` and a `.debug/` directory containing corner overlay, rectified facade and all three atlas maps. The supplied source bundle contains every new file verbatim.

## 5. Install on Apple Silicon

```bash
cd backend
python3.12 -m venv .venv-footprint
.venv-footprint/bin/python -m pip install -r requirements-footprint.txt
.venv-footprint/bin/python -m pip install pytest
```

Or install `requirements-footprint.txt` into the existing backend virtualenv to call it from the existing Python pipeline. Requirements use compatible major-version ranges rather than replacing the app's existing pins.

## 6. Process one existing building

From `backend`:

```bash
.venv-footprint/bin/python scripts/build_footprint_asset.py \
  --image assets/samples/burruss_scorched.png \
  --footprint assets/samples/burruss_footprint.json \
  --state scorched \
  --output /tmp/scorched-nebraska/burruss_hybrid.glb
```

Optional `--camera-bearing`, `--edge`, `--height`, `--texture-size` and `--corners` override ambiguous observations. The edge list in the report uses normalized winding; do not assume indices match the original input ring order.

Python integration after the existing image edit/rembg step:

```python
from app.generation.footprint_asset import build_asset

report = build_asset(
    image_path="edited_building.png",
    footprint=selected["geometry"],
    footprint_crs_or_latlon="EPSG:4326",
    longest_edge_bearing=selected["rotationDegrees"],
    footprint_dimensions=(selected["footprintWidthMeters"],
                          selected["footprintDepthMeters"]),
    osm_tags=selected.get("tags", {}),
    output_path="building.glb",
    world_state="scorched",
    # If known: camera_bearing=building_to_camera_bearing,
    # If known: facade_corners=[[120, 420], [1120, 370], [1140, 615], [105, 640]],
)
```

The commented corners illustrate the parameter shape, not a calibrated Burruss facade. One quadrilateral must describe one wall plane, not a multi-depth tower plus wings.

A standalone JSON object with the same arguments can also be run using:

```bash
.venv-footprint/bin/python -m app.generation.footprint_asset.pipeline building.json
```

Deck.gl integration with the **current repository's axis convention**:

```ts
const placement = report.placement;
const layer = new ScenegraphLayer({
  id: 'footprint-building',
  data: [{ position: report.longitude_latitude }],
  scenegraph: servedGlbUrl,
  getPosition: d => [d.position[0], d.position[1], terrainHeight],
  getOrientation: report.deck_orientation, // [0, yaw, 90]
  getScale: [1, 1, 1],
  sizeScale: 1,
  _lighting: 'pbr',
});
```

To persist into the current app, serve/upload the GLB using the existing storage mechanism and use the report's placement values. `placement.position` is `[lat,lng,0]`, matching the existing backend record; `longitude_latitude` is `[lng,lat]`. Use the compensated report anchor, not the original OSM centroid. Local-meter input has no geographic origin and returns null position; the caller must georeference it. Do not pass this asset through the old mesh normalization or rectangle-based placement fitting stages again: it is already in meters and precisely shaped. For async API handlers, execute this synchronous builder in a worker thread. The supplied adapter is an executable integration path; existing HTTP contracts and provider selection remain unchanged.

## 7. Runtime

The report times actual execution on the host. Working budgets after an edited image exists (CPU, no model load):

| Stage | Engineering budget, not an M5 benchmark guarantee |
|---|---:|
| CRS/height/edge selection | <1 s |
| Rectification and approximate delighting | 0.1–2 s |
| Atlas generation, geometry and GLB encoding | 0.5–8 s |
| Serialized validation and diagnostics | 0.2–3 s |

These leave substantial room under two minutes for this stage. Existing image editing, optional segmentation and free-Space queues are outside this measurement. Do not promise an end-to-end two-minute deadline for those services.

## 8. Validation

```bash
cd backend
.venv-footprint/bin/python -m pytest tests/test_footprint_asset.py -q
```

Each output is reloaded from its serialized GLB. Checks cover finite vertices, nonzero triangle areas, unit normals, exported NORMAL and TEXCOORD_0 attributes, valid UVs, Y minimum, centered pivot, height, <=30k triangles, both footprint-frame dimensions within 0.1%, roof silhouette IoU >0.999 including holes, one material, three valid power-of-two texture images, and compressed file budget. No GLB is written on a failed validation.

The sample regression explicitly enforces 101.88 × 70.79 instead of the failed 101.88 × 37.57 dimensions. Additional tests cover concavity, courtyards, separate polygon parts, floor winding, camera bearings, projected CRS, unmirrored front UVs, sharp roof normals, invalid coordinates/corners and budget failure. PASS means geometric/file validity, **not** visual approval of a guessed facade.

Inspect `.debug/facade-corners.png` and `.debug/facade-rectified.png`. An automatically found eave/base band can omit the tower; an inset fallback may still include background. Four-point override and correct camera/edge metadata are the highest-value corrections for hero assets. The generated roof is flat even if the image is not.

## 9. Repeatable A/B comparison

Use at least ten buildings: rectangles, L shapes, courtyards, a tower, a small building and a strongly oblique photo. Use identical edited images, OSM geometry, map anchor, sun, exposure, viewport (e.g. 1440×900, device pixel ratio 1), browser and hardware. Compare the existing GLB (A) with this GLB (B). Repeat B once automatically and once with confirmed facade corners/association; report them separately to expose manual effort.

| Metric | Measurement and acceptance |
|---|---|
| Footprint silhouette | Project triangles onto the ground in the known bearing frame, union them and compute intersection/union with the target polygon. Include holes. B >0.999; record A without rescaling its depth. |
| Roofline straightness | In orthographic facade renders, mark the same intended straight cornice/eave segments, fit a line, report RMS perpendicular error in meters. Also score silhouette fidelity separately: a flat replacement can be straight but architecturally wrong. |
| Vertical-edge deviation | Mark the same wall corners; measure degrees from world up and RMS line error. Separate lost/missing edges from straight ones. |
| Facade texel density | Report atlas pixels per wall meter in both directions AND original source pixels per meter. A larger atlas does not recover new detail. |
| Texture stretching | Use an asymmetric labeled checkerboard image in both pipelines; measure horizontal/vertical grid spacing distortion on the photographed plane, sides and rear. No mirrored labels. For real photos count elongated/duplicated windows. |
| Backside quality | Fixed rear and two side views; count copied facade features, obvious seams and nonsensical structures. Score neutral but coherent surfaces separately from detail richness. |
| Baked-shadow visibility | Render under diffuse-only light, then with directional light rotated 180°. Compare the same wall patches for persistent dark/bright patterns. Keep world-state burns distinct from lighting artifacts. |
| 50, 100, 200 m | Fix actual eye-to-building distance, 45° elevation and 50° FOV in a perspective inspection camera (map zoom alone is not a distance). Capture front, rear and oblique screenshots. Also record map screenshots with the exact deck viewState. Blind-score identity, silhouette, facade and artifacts. |
| GLB size | On-disk bytes from report; B <=3,000,000 by default. |
| Load time | Browser Performance panel: cold uncached request start to first correct rendered frame; measure warm runs separately. Ten runs, median and p95. Include GLTF decode and GPU upload, not just download. |
| FPS with ten buildings | Ten **different** GLBs, same 30-second orbit and viewport. Record browser frame-time median/p95, long frames >33 ms, memory and texture tier. Test 2048 and 1024 separately. Do not reuse a single instanced asset as the ten-building result. |

Gate deployment on correct position, upright front, no mirrored UVs, complete roof holes, no GLB errors and acceptable map views. Run the existing `tests/viewer/deck_check.html` for axis sanity with `mesh`, `yaw`, `w`, `d` URL parameters; its rectangle overlay is not a polygon-IoU test and uses a fixed anchor. Set yaw from the report, and use model-frame X/Z extents for that rectangle. Use the actual application for final OSM polygon placement and ten-asset FPS. Browser visual quality, load times and FPS have not been claimed as measured by the offline Python tests.

## 10. Deliberately rejected components

These are implementation decisions, not claims from a comparative M5 benchmark:

- **Zero123++:** generates synthetic views, not new observations; it does not make hidden architectural measurements reliable. Its standard example uses CUDA, and adding it plus reconstruction needs an unproven MPS/runtime path. [Official repository](https://github.com/SUDO-AI-3D/zero123plus).
- **SV3D:** view synthesis adds a diffusion stage; official sampling defaults to CUDA. No demonstrated benefit under this project's two-minute/24 GB MPS limit, and it does not enforce OSM. [Official sampling implementation](https://github.com/Stability-AI/generative-models/blob/main/scripts/sampling/simple_video_sample.py).
- **Wonder3D:** official installation uses tiny-cuda-nn; no CUDA on this host. [Official README](https://github.com/xxlong0/Wonder3D/blob/main/README.md).
- **InstantMesh:** official inference explicitly selects CUDA and its setup installs CUDA. Reject an unsupported port plus synthesized views for this hackathon. [Official inference](https://github.com/TencentARC/InstantMesh/blob/main/run.py).
- **CRM:** official setup uses CUDA PyTorch, torch-scatter, Kaolin and nvdiffrast. Its advertised runtime is not an Apple MPS runtime. [Official repository](https://github.com/thu-ml/CRM).
- **Stable Fast 3D / TripoSR:** retain the project's existing implementations for A/B assets, but neither is called here. Replacing their guessed massing removes the observed depth/base failures rather than trying to planarize inconsistent surfaces. [SF3D](https://github.com/Stability-AI/stable-fast-3d), [TripoSR](https://github.com/VAST-AI-Research/TripoSR).
- **Real-ESRGAN / SwinIR:** real restoration models, but a 1280-pixel photo cannot gain measured facade detail just by enlarging it. Default is Lanczos/unsharp with source-density reporting; avoid another checkpoint and hallucinated repetitive window details without demonstrated map-scale benefit. No neural SR is claimed. [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN), [SwinIR](https://github.com/JingyunLiang/SwinIR).
- **Heavy intrinsic decomposition, learned normals, displacement, mesh planarization/decimation:** not included. Bounded delighting and gentle normal cues are approximations; deterministic planes already preserve wall normals, sharp intersections, flat ground and exact footprint. There is no learned geometry left to clean, and no reason to smooth or inflate the triangle count.

Synthetic multiview might improve generic object plausibility; this implementation does not claim to experimentally disprove that. The decision here follows the absence of actual new measurements, unsupported dependencies in several candidates, and the known importance of OSM dimensions. True building-part footprints/heights or calibrated additional real photos would address the remaining roof/tower limitations more directly.

## Recorded local sample (this implementation session)

Input: repository `burruss_scorched.png` and selected `burruss_footprint.json`, default automatic facade/edge selection. Output: 101.880002 × 70.790003 × 20.700001 m in footprint W/D/H frame; footprint IoU 0.999999969; 390 triangles; one material; 2048² PBR atlas images; 1.30 MB; Y minimum zero. Measured stages: CRS/height 0.011 s, rectification/delighting 0.118 s, materials/geometry/export 0.417 s, validation 0.046 s, total including diagnostic writes 0.971 s. Single host run, not a runtime guarantee or full FLUX benchmark.

53 targeted tests passed across the new module and existing normalization, geo-math and placement tests. Inspected the geometry render and corner-overlay image. The automatic band avoids most sky but is still low confidence and includes some ground; it is not an approved hero facade. Its tower/wing planes cannot be rectified correctly by one homography. No browser PBR render, ten-building FPS run or blind visual A/B result is claimed.
