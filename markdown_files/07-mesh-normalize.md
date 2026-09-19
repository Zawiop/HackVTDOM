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
