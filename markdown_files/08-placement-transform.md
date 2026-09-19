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
