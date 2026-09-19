# Function: normalizeMesh

## Purpose
Different mesh sources use different conventions — pivot at a corner vs. center, "up" axis as Y vs. Z, inconsistent real-world scale units. This function makes every mesh consistent before step 08's placement math runs. The spec's own line covers all four: normalize units, axes, orientation, and pivot — skipping any one of them is what causes a mesh to render sideways, floating, or the wrong size live in front of judges.

## Cost / auth
None. Pure geometry processing, runs locally (Python + `trimesh`, or a Blender headless script) — no external call.

## Inputs
The raw mesh file from step 06 (TripoSR's output — verify in that file's CAPTURED EXAMPLE whether it's `.obj` or `.glb`; TripoSR's own pipeline typically outputs `.obj` with a texture, which needs a straightforward one-line export to `.glb` before or during this step for deck.gl's glTF loader downstream).

## Steps this function must perform, in order
1. **Unit check.** Verify or convert the mesh's scale to meters. Sanity-check the result against `footprintWidthMeters` from step 02 — if the mesh's largest dimension is wildly inconsistent with the known footprint (e.g. off by more than ~3-4x), treat it as a units problem, not a scale-fitting problem, and correct before step 08 runs. Skipping this silently corrupts the scale factor computed in step 08, since that math assumes units are already correct.
2. **Up-axis correction.** TripoSR and similar image-to-3D tools commonly output Y-up; deck.gl's `ScenegraphLayer` expects a specific convention (see step 12) — rotate the mesh so its up axis matches what the renderer expects, don't rely on the renderer to compensate.
3. **Pivot re-centering.** Move the mesh's origin/pivot to its base-center (not a corner, not its bounding-box center in all three axes — base-center, so the ground-alignment math in step 08 has a clean z=0 reference at the bottom of the mesh).
4. **Orientation sanity pass.** After 1-3, do one visual check (render it once, look at it) before wiring it into the automated pipeline — this step is cheap insurance specifically because it's mechanical and easy to get subtly wrong in a way that only shows up as "this one building looks off" during a live demo.

## Output
A `.glb` file with meters-correct scale, consistent up-axis, and a base-centered pivot, ready for step 08.

## Failure handling
If unit sanity-check fails badly (mesh is nonsensically large or small relative to the known footprint) and no reasonable correction factor is obvious, flag `confidence: "low"` and route to manual correction (step 09) rather than guessing a scale factor that might be very wrong.

## VERIFIED OUTPUT CONVENTION (2026-09-19) — what steps 08 and 12 can rely on
Implemented in `backend/app/generation/mesh_normalize.py`, run inside `POST /api/generate-mesh` (and
standalone as `POST /api/mesh/normalize` to re-fit a mesh once the real footprint is known).

Every returned `.glb` is:
- **glTF +Y up**; the **photographed facade faces +Z**; +X is the viewer's right when facing the facade.
  (SF3D's raw output is +Y up with the facade at −Z — verified from its export code and by render —
  so normalization applies a 180° yaw. The placeholder is authored in-convention.)
- **Squared up**: the mesh's minimum-area ground rectangle is rotated onto X/Z by the smallest yaw
  (≤ 45°), because street photos are taken at an angle and the raw mesh sits diagonally (22–27° on
  the Burruss test photos). Without this the bounding box measures a diagonal and step 08's
  0/90/180/270 candidates miss the real walls.
- **Meters**. Unit check: image-to-3D output is unitless (~1-unit box), so the longest horizontal
  side is fitted to the longest footprint side. For meshes declared to be in meters, a mesh within
  3.5x of the footprint is left alone; one further off is converted only if a cm/mm/in/ft factor
  lands within 2x, otherwise it is left unscaled and flagged `auto-low` (never a guessed factor).
  No footprint supplied → sized to 20 m with a warning; step 08 rescales.
- **Pivot at base-center**: X/Z bounding-box center, lowest point at y = 0. Tiny disconnected
  floaters (< 0.5% of faces, measured on a position-welded copy so UV seams don't count) are
  dropped first so they can't drag the base down.
- Exported with `NORMAL` (+ `TEXCOORD_0` and the baseColor texture).

**Visual check done** (step 4 above): rendered with matplotlib from 4 views (`backend/scripts/render_mesh.py`)
and in deck.gl 9 + MapLibre at Burruss Hall's real coordinates (`backend/tests/viewer/deck_check.html`,
served at `/debug/deck_check.html` when `DEBUG_VIEWER=1`). With `getOrientation: [0, yaw, 90]`:
upright, textured, base on the ground, not mirrored. **At yaw 0 the facade faces south; at yaw 90 it
faces east** (checked by looking west at yaw 90 and seeing the entrance head-on) — so the facade's compass
bearing is `180 − yaw`, and mesh +X points east at yaw 0.

Real sample outputs to test against: `backend/assets/samples/` (Burruss Hall, scorched + flooded,
fitted to its real 101.88 x 70.79 m OSM footprint).
