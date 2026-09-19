# Function: computePlacementTransform

## Purpose
The actual geometry core of the challenge: correct rotation, scale, and ground alignment for the normalized mesh (step 07) against the real footprint (step 02). No external service — pure computation.

## Cost / auth
None.

## Rotation
Do not trust a single guess from the footprint's longest edge. Generate candidate rotations: the longest-edge bearing from step 02, plus that angle ± 0/90/180/270 degree offsets. For each candidate, rotate the mesh's footprint (its base outline) and compute IoU (intersection-over-union) against the real OSM polygon from step 02. Keep whichever candidate scores highest. Keep the full scored list, not just the winner — step 09's correction UI reuses it as "try these 4 alignments" buttons, so don't discard the computation.

## Scale
Default to a single uniform scale factor that fits the mesh to both `footprintWidthMeters` and `footprintDepthMeters` as closely as possible (matches "proportion-preserving" scaling, called out as a stated preference in the source spec). Only fall back to independent width/depth stretching if uniform scaling would leave the mesh badly undersized relative to the footprint — define "badly" as a concrete threshold (e.g. more than ~30% smaller on one axis) rather than eyeballing it per building.

## Collision
Reuse the neighboring footprints already pulled from Overpass in step 02 — no new API call. Run a bounding-box overlap test between the placed mesh's footprint and each neighbor. If overlap exceeds a threshold, flag `confidence: "low"` here, tracked separately from the footprint-match flag in step 02 (these are two distinct uncertainty sources and step 09 needs to know which one it's showing).

## Ground alignment
Set the z-coordinate so the mesh's base (its now-centered pivot, from step 07) sits at ground level — not floating above, not sinking below.

## Output
A transform record: `{ rotationDegrees, scale, position: [lat, lng, z], confidence: "auto-high" | "auto-low", scoredRotationCandidates: [...] }`. This full record is what gets written to Supabase in step 11 and what step 09's correction UI reads and mutates.

## Failure handling
Any of the three sub-steps flagging low confidence sets the overall record to `auto-low` and routes to step 09. Don't let one flagged sub-check get silently overwritten by a later "everything's fine" check.

---

## IMPLEMENTATION NOTES — 2026-09-19

Implemented in `backend/src/services/placement.ts`, with the geometry in `backend/src/geo/`.
Ground-truth tested against 40 real OSM building polygons around VT (checked in at
`backend/test/fixtures/osm-footprints.json`) by extruding a real footprint into a mesh with a known
rotation/scale/offset baked in, and asserting placement recovers it. Result on that set: rotation
recovered to **0.00°**, scale to **1.0000**, position to within **7 cm**, fit quality **1.000**.

Three places where the spec above needed sharpening. Full reasoning in `STATUS.md`.

### Measured: the longest edge is not a usable orientation estimate here
The mesh base outline is a convex hull; a real OSM footprint frequently is not, and a hull edge that
bridges a concave notch is long while saying nothing about how the building is oriented.

Across the 12 buildings measured, the **minimum-area-rectangle angle of a polygon and of its own
convex hull agree to 0.000°**. Their **longest edges disagree by up to 65°** (Hancock Hall: footprint
137.1°, hull 162.9°). Using the longest edge put Hancock Hall 29 m from its own footprint and
Campbell Hall 28 m away; the min-area rectangle puts both within 5 cm.

So the rotation search aligns min-area-rectangle axes. Step 02's longest-edge bearing is still
accepted, cross-checked against the polygon, and reported — it is just not what the search runs on.

### The candidate formula needs the mesh's own orientation
"The longest-edge bearing from step 02, plus ± 0/90/180/270" assumes the mesh arrives with its long
axis pointing north. A mesh reconstructed from a photograph does not — TripoSR orients output to the
camera. Implemented as:

```
heading = footprintPrincipalAxis − meshPrincipalAxis + offset      offset ∈ {0, 90, 180, 270}
```

This reduces to the formula above when the mesh axis is 0, and the four candidates stay exactly 90°
apart, so step 09's "try these 4 alignments" buttons are unaffected.

### An absolute IoU threshold cannot work across these buildings
Because the mesh outline is convex, the best IoU *any* mesh could score against a given footprint is
that footprint against its own hull — **0.48 for Campbell Hall, 0.98 for Sandy Hall**. A single
threshold would flag a perfect placement on the concave buildings and pass a bad one on the simple
ones. Confidence judges `fitQuality = iou / maxAchievableIou` instead; both numbers are reported.

### Measured: flagging the 180-degree flip is not informative
Comparing the winner to the runner-up flagged **44% of the real footprints, and every single one was a
pure 0-vs-180 pair.** A building footprint is very nearly centrosymmetric, so IoU cannot separate a
facade from its back in principle — flagging it routes half of all placements to manual review over a
distinction the algorithm never had the information to make.

Ambiguity is judged against the best *geometrically distinguishable* alternative instead (the 90°
turns, where the mesh sits across the footprint rather than along it). The flip margin is still
reported so step 09 can offer a "turn it around" control.

### Collision: bounding box as the gate, polygons as the verdict
The bounding-box test above is kept as the cheap first pass. But campus is laid out at roughly 45° to
the compass, so axis-aligned boxes overlap constantly while the buildings are metres apart. A box hit
is confirmed against the actual polygons before it counts as a collision. Also, "overlap exceeds a
threshold" needs a denominator: measured against the mesh alone, a large building completely covering
a small neighbour scores ~5% and passes, so it is `max(overlap/mesh, overlap/neighbour)`.

### One addition
**Offset refinement.** Centroid-matching a convex hull to a concave footprint is off by a couple of
metres. A shrinking-step hill climb on the same IoU objective recovers it.

### Result across the whole fixture set
All 32 real VT footprints, each placed against a mesh built from itself and checked against all its
real neighbours: **32/32 `auto-high`, zero flags.** Before the two corrections above, 44% were
`auto-low` on the flip and a further batch on phantom bounding-box collisions.

### Note for step 12
`scaleXYZ` assumes deck.gl's ScenegraphLayer order — **scale in model space, then rotate, then
translate**. The IoU search mirrors that order exactly, so a score computed here is the score you see
on the map. Applying them in another order misplaces non-uniformly-scaled meshes.
