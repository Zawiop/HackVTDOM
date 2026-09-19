# STATUS — input layer + geometry core

Owner of steps **03** (photo input), **04** (World State prompts) and **08** (placement transform).
Everything below is what the next person needs to know that isn't obvious from the code.

Last updated: 2026-09-19.

---

## What's done

| Step | State | Where |
|---|---|---|
| 03 photo input | Done, verified against the live Mapillary API | `backend/src/services/{mapillary,photoInput,photoStore}.ts`, `backend/src/routes/photos.ts`, `frontend/src/components/PhotoInput.tsx` |
| 04 World State | Done | `backend/src/services/worldState.ts`, `backend/src/routes/worldState.ts`, `frontend/src/components/WorldStateSelector.tsx` |
| 08 placement | Done, ground-truth tested on real OSM footprints | `backend/src/services/placement.ts`, `backend/src/geo/{latlng,polygon,mesh}.ts`, `backend/src/routes/placement.ts` |

102 backend tests + 17 frontend tests. `cd backend && npm run verify` runs typecheck, tests and the smoke script.

---

## Blocking / needs someone else

### 1. No push access to the repo
`git push` fails: `Permission to Zawiop/HackVTDOM.git denied to autobot433`. All the work above is
committed **locally only**. Whoever owns the repo needs to add `autobot433` as a collaborator, then
this branch can go up. Pulling works fine.

### 2. Steps 01/02 and 05/06/07 have not landed
As of the last `git fetch`, `origin/main` still contains only the markdown files and a README —
no teammate code. So step 08 has **never been run against a real `/api/footprint` response or a real
TripoSR mesh**. It has been run against:

- **Real OSM footprints** — 40 real building polygons around VT pulled from the same Overpass query
  spec 02 specifies, checked in at `backend/test/fixtures/osm-footprints.json`.
- **Real binary glTF** — `Box.glb` and `Duck.glb` from the Khronos sample set, to exercise the GLB
  parser including node transforms.
- **Ground-truth meshes** — real OSM footprints extruded into solids with a known rotation, scale and
  vertical offset baked in, so "correct" means "recovered exactly what was applied", not "looked fine".

**What still needs checking when their routes land** is listed under *Integration checklist* below.

---

## Decisions someone should know about

### The API is `backend/` + `frontend/`, not the README's layout
`README.md` describes `apps/api/`, `apps/web/`, `packages/shared/`, and a stack of
Mapbox + Replicate + Tripo3D. Both are stale: the `.env` files were already sitting in `backend/` and
`frontend/`, and `markdown_files/00-overview.md` supersedes the stack (Nominatim, Gemini, TripoSR,
MapLibre). I followed the `.env` layout and the overview. **The README is worth correcting before
judging** — a judge reading it will be told the wrong stack.

### Route registry in `backend/src/app.ts`
Four people adding routes to one Express app. Each module owns one file under `src/routes/` and adds
one line to the `ROUTES` array. Adding `/api/footprint` or `/api/mesh` should be a one-line diff.

### Uploads go to local disk for now
`backend/uploads/`, served at `/uploads/...`. Whoever does step 11 should swap the body of
`storePhotoBytes()` in `backend/src/services/photoStore.ts` for a Supabase Storage upload — it is
deliberately the only place that touches the filesystem, so nothing else has to change.

---

## Things found that are worth your time

### Mapillary's bbox index is non-deterministic
Five **byte-identical** requests to a known-dense area returned **0, 2, 5, 6, 5** images. A single
empty `data` array is frequently a false negative. Handled with a retry ladder; full write-up and a
captured request/response pair are appended to `markdown_files/03-photo-input.md`.

Also: **Blacksburg has coverage** (spec 03 listed it as untested). Burruss Hall returns 7 captures,
nearest 23 m, most recent 2024-10-11.

### Overpass returns 406 without a real User-Agent — for step 02's owner
`overpass-api.de` returned `406 Not Acceptable` to plain `curl`, and `200` to the identical request
with `User-Agent: ScorchedNebraskaVTHacks/1.0 (...)`. Spec 02 mentions 406s under load but attributes
them to rate limiting; at least some of them are just the missing header. It also 429s readily —
`https://overpass.kumi.systems/api/interpreter` worked every time the primary did not.

Second thing for step 02: at `(37.2284, -80.4234)` — the coordinate with the best Mapillary coverage —
`around:50` returns **zero** buildings. You need ~200 m to reach Davidson/Derring/Norris. Spec 02's
"widen if a demo address returns nothing" is not an edge case here, it is the normal path.

### A bug the test suite could not see
`polygon-clipping` is CommonJS. Imported as `import * as polygonClipping`, Vite hands back a callable
namespace but Node's ESM interop puts the functions on `.default` — so **every IoU silently returned 0
under `npm start` while the entire test suite stayed green**. Fixed by importing the default export,
plus a load-time assertion in `backend/src/geo/polygon.ts`.

`backend/scripts/smoke.ts` (`npm run smoke`) exists specifically to catch this class of bug: it runs
the real pipeline under tsx/Node rather than through Vite. **Worth running before judging** — it is
about two seconds and it checks the thing that looked fine right up until it didn't.

---

## Where step 08 deviates from `08-placement-transform.md`, and why

All three of these are documented in the code at the point they happen.

### 1. Candidate rotations account for the mesh's own orientation
The spec says candidates are "the longest-edge bearing from step 02, plus that angle ± 0/90/180/270".
Taken literally that assumes the mesh arrives with its long axis pointing north. A mesh reconstructed
from a photograph does not — TripoSR orients output to the camera. So the heading is:

```
heading = footprintPrincipalAxis − meshPrincipalAxis + offset      offset ∈ {0, 90, 180, 270}
```

which reduces to the spec's formula when the mesh axis is 0. The four candidates are still exactly
90° apart, which is all step 09's "try these 4 alignments" buttons need.

### 2. Principal axis comes from the minimum-area rectangle, not the longest edge
The mesh base outline is a **convex hull**; a real OSM footprint often is not. A hull edge bridging a
concave notch is long but says nothing about orientation. Measured on the real fixtures: the
min-area-rectangle angle of a building and of its own convex hull agree to **0.000°** across all 12
buildings checked, while their longest edges disagree by up to **65°**.

Using the longest edge put Hancock Hall **29 m** from its footprint and Campbell Hall **28 m** away.
With the min-area rectangle both land within **5 cm**. Step 02's longest-edge bearing is still
accepted, cross-checked and reported in `diagnostics.longestEdgeBearingDegrees`.

### 3. Confidence judges *fit quality*, not an absolute IoU
Because the mesh outline is convex, the highest IoU any mesh could score against a given footprint is
that footprint against its own hull — **0.48 for Campbell Hall, 0.98 for Sandy Hall**. One absolute
threshold would flag a perfect placement on the concave buildings and wave a bad one through on the
simple ones. So `fitQuality = iou / maxAchievableIou`, and the flag fires below 60% of achievable.
Both numbers are in `diagnostics`.

### 4. The 180° flip is reported, not flagged
Comparing the winning rotation to the runner-up flags a lot of buildings — measured across the real
fixtures, **44% of placements had their top two candidates within the margin, and every one of them
was a pure 0-vs-180 pair.** A footprint is very nearly centrosymmetric, so IoU cannot tell a facade
from its back, in principle. Flagging that would route half of all placements to manual review to
resolve a distinction the algorithm was never able to make.

Ambiguity is now judged against the best *geometrically distinguishable* alternative — the 90° turns,
where the mesh really would sit across the footprint instead of along it. The flip margin is reported
as `diagnostics.rotationFlipMargin` so step 09 can still offer a "turn it around" button, and all four
candidates are in the list regardless.

### 5. Collision confirms box hits against the real polygons
Spec 08 asks for a bounding-box overlap test, and that is kept — as the cheap gate. But campus is laid
out at roughly 45° to the compass, so axis-aligned boxes overlap constantly while the buildings are
metres apart. A box hit is now confirmed against the actual polygons (exact clipping, already in the
codebase) before it counts. Spec 08 also says overlap "exceeds a threshold" without saying of what:
measured against the mesh alone, a large building swallowing a small neighbour scores ~5% and passes,
so it is `max(overlap/mesh, overlap/neighbour)` with both reported.

### Also added, not in the spec
**Offset refinement.** Centroid-matching a convex hull to a concave footprint is off by a couple of
metres. A shrinking-step hill climb on the same IoU objective fixes it; `diagnostics.refinementShiftMeters`
records how far it moved.

### The result on real data
All **32** real VT footprints, each placed against a mesh built from itself and checked against all
its real neighbours: **32/32 auto-high, zero flags**, rotation recovered to 0.00°, scale 1.0000,
position within 7 cm. Before the two fixes above, 44% were auto-low on the flip and a further batch on
phantom box collisions.

---

## Contract for step 08 — what to send it

`POST /api/placement`

```jsonc
{
  "footprint": {
    "polygon":   { "id": 26210244, "geometry": [{ "lat": 37.2, "lng": -80.4 }, ...] },
    "neighbors": [ { "id": 43082478, "geometry": [...] }, ... ],   // from step 02's cache, not a re-fetch
    "footprintWidthMeters": 60.2,          // optional; cross-checked, not trusted
    "footprintDepthMeters": 31.4,          // optional
    "longestEdgeBearingDegrees": 135.6,    // optional
    "confidence": "high"                   // "low" propagates into the record
  },
  "mesh": {
    "path": "/abs/path/normalized.glb",    // or "url", or "bytesBase64"
    "upAxis": "y"                          // glTF default; step 07 owns this
  }
}
```

`footprint.geometry` is accepted as an alias for `footprint.polygon.geometry`.
Response is the `PlacementTransform` in `backend/src/types/placement.ts` — the five fields spec 08
names, plus `scaleXYZ`, `flags`, `collision`, `ground` and `diagnostics`.

### For step 12 (deck.gl)
`scaleXYZ` is in renderer order and assumes the ScenegraphLayer's own transform order —
**scale in model space, then rotate, then translate**. The IoU search mirrors that order exactly, so a
score computed here is the score you see on the map. Applying them in a different order will place
non-uniformly-scaled meshes wrong. `position` is `[lat, lng, z]`; `z` is metres, and is 0 whenever
step 07 base-centred the pivot properly.

### For step 09 (correction UI)
`scoredRotationCandidates` is the full sorted list of four, each with its `iou`, `scale` and
`coverage` — nothing is discarded. `flags[]` carries a `subStep` of
`footprint | rotation | scale | collision | ground | mesh`, so the UI can tell a step-02 footprint
problem apart from a step-08 placement problem. Confidence is **derived from the flags at the end**
rather than assigned as it goes, so there is no intermediate value for a later clean check to
overwrite — spec 08's explicit requirement.

---

## Integration checklist — when 01/02 and 05/06/07 land

1. **Run step 08 against a real step 02 response.** If `diagnostics.footprintDerivedMismatch` is
   populated, step 02's width/depth/bearing disagree with the polygon it sent. Placement uses values
   computed from the polygon and flags the disagreement rather than silently picking one.
2. **Run step 08 against a real TripoSR mesh.** Two flags to watch for, both pointing upstream:
   - `implausible-scale` — the mesh is not in metres; that is step 07's unit check.
   - `pivot-not-base-centred` — step 07 did not base-centre the pivot. Placement corrects for it and
     says by how much, but step 07 should fix it at source.
3. **Confirm the mesh up-axis.** Default is `y` (glTF). If step 07 emits Z-up, pass `upAxis: "z"` —
   this is **not** auto-detected on purpose. Guessing it would silently paper over a step 07 bug, and
   a mesh read on the wrong axis produces a wrong-but-plausible footprint.
4. **Check `fitQuality` on a real generated mesh.** TripoSR output from a single photo will not match
   an OSM footprint as well as the ground-truth fixtures do. If good placements routinely land in the
   0.4–0.6 band, `minFitQuality` (default 0.6) wants lowering — the threshold is a `PlacementOptions`
   field, not a constant, for exactly that reason.
5. **Pre-cache the demo buildings.** Spec 00 and spec 02 both say so. Davidson, Derring, Norris and
   War Memorial Hall are already captured in the test fixtures and all place cleanly.

---

## Not mine, not touched

Steps 01, 02, 05, 06, 07, 09, 10, 11, 12, 13. The only shared files I edited are
`backend/src/app.ts` (route registry), `.gitignore`, and `markdown_files/03-photo-input.md`
(appended the verified API capture that file asks for).
