# Function: correctionControls (frontend-heavy, mostly no new backend logic)

## Purpose
Close the gap the spec's placement checklist leaves open: "send uncertain results for manual review" needs an actual way for a human to fix it, not just a visual flag. This is almost entirely frontend work reusing data steps 02 and 08 already computed — budget roughly 2-3 hours, mostly UI, per the original plan's own estimate.

## Cost / auth
None. No new external calls — every control here binds to fields already computed by steps 02/08.

## Two distinct low-confidence cases, each with its own fix

**Footprint-match uncertainty (from step 02).** When Overpass returned multiple equally-close candidates, show all of them as selectable outlines on the map instead of auto-picking the nearest centroid. One click confirms the right one and re-runs step 08 with that footprint.

**Placement uncertainty (from step 08).**
- Rotation: surface the already-scored candidate rotations (longest-edge angle + 0/90/180/270 offsets) as buttons, each labeled with its IoU score. One click swaps the mesh to that rotation live — no recomputation needed, the scores already exist.
- Scale: a slider bound to the uniform scale factor, live-updating the mesh in the deck.gl view.
- Position/collision: arrow-key nudging (0.5m per press, 5m with shift) on the mesh's lat/lng, re-running the step 08 collision check live so the overlap warning clears as the mesh moves off a neighbor.

## Why buttons/sliders instead of freeform 3D dragging
Correct screen-to-world projection for dragging a 3D object on a deck.gl `ScenegraphLayer` is a real engineering sink under a hackathon clock. Controls bound to the same transform fields already being stored get most of the practical value for a fraction of the risk — don't build freeform dragging even if there's spare time; put that time into steps 10/11/13 instead.

## Confidence states (three, not two)
`auto-high` (algorithm was confident and correct), `auto-low` (flagged, needs review), `manually-verified` (a human corrected it via this UI). On save, write the adjusted rotation/scale/position back to the same Supabase row and flip its state to `manually-verified` — don't silently overwrite it as if the algorithm got it right the first time. This third state is also the strongest technical-depth beat in the pitch (step 14): "here's one we flagged, and here's a human closing the loop the algorithm couldn't."

## Output
Same transform record shape as step 08, with `confidence` updated to `manually-verified` and the corrected values, written via step 11.
