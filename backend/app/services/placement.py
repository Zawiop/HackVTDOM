"""Step 08 -- computePlacementTransform (08-placement-transform.md).

Rotation, scale, ground alignment and a collision check for the normalized mesh
from step 07 against the real OSM footprint from step 02. No external calls.

All geometry happens in a local meter plane anchored on the footprint centroid,
so the IoU search is ordinary 2D polygon math. See `placement_geom`.

Frames, because getting this wrong is invisible until a building is sideways
on a map:

* Step 07 hands over glTF convention -- +Y up, facade facing +Z, meters,
  origin at base-center -- and has already squared the ground outline up with
  X/Z and scaled the longest horizontal side to the footprint.
* glTF is right-handed, so with Y up the geographic mapping that is a rotation
  rather than a mirror is **east = +X, north = -Z**. Mapping +Z to north instead
  would reflect the mesh, which silently costs IoU on any asymmetric building.
  Step 07's own note agrees: at yaw 0 the facade faces south, i.e. +Z is south.
* Internally this module works in compass headings (0 = north, clockwise). The
  renderer wants deck.gl's yaw, where facade bearing = 180 - yaw, so the two run
  opposite: **yaw = -heading**. Everything named `rotationDegrees` on the way out
  is already yaw, because that is what `layers.js` feeds straight into
  `getOrientation`.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..services import placement_geom as g
from ..services.geo_math import meters_per_degree, polygon_centroid

# Spec 08: the longest-edge bearing, "plus that angle +/- 0/90/180/270 offsets".
ROTATION_OFFSETS = (0, 90, 180, 270)

DEFAULTS: Dict[str, float] = {
    # "more than ~30% smaller on one axis" -> coverage below 0.70.
    "undersizeThreshold": 0.70,
    "collisionThreshold": 0.15,
    # Judged as a fraction of what a convex outline can achieve -- see below.
    "minFitQuality": 0.60,
    "rotationAmbiguityMargin": 0.05,
    # Aspect distortion past which a non-uniform fit stops being the expected
    # single-view depth correction and starts being "a human should look".
    "extremeStretchRatio": 2.5,
}

# A fit factor this far from 1 means step 07 handed over a mesh that is not in meters.
IMPLAUSIBLE_SCALE_RATIO = 4.0


class PlacementInputError(ValueError):
    """Bad input, as opposed to a server fault. The router turns this into a 422."""


class _Ledger:
    """Collects flags and derives confidence, latching low once anything sets it.

    Spec 08: "Any of the three sub-steps flagging low confidence sets the overall
    record to auto-low ... Don't let one flagged sub-check get silently
    overwritten by a later 'everything's fine' check." Confidence is derived from
    the accumulated flags at the very end rather than assigned as the algorithm
    goes, so there is no intermediate value for a later step to overwrite.

    Flags carry a severity because not everything worth recording is a reason to
    stop trusting the result. A confidence signal that fires on every building
    tells step 09 nothing -- measured on the real sample meshes, the
    single-view depth shortfall fires 100% of the time, because guessing depth
    from one photograph is what the pipeline does, not an anomaly. Those are
    recorded as `info`; only `low` moves the record to auto-low.
    """

    def __init__(self) -> None:
        self._flags: List[Dict[str, str]] = []

    def flag(self, sub_step: str, code: str, message: str, severity: str = "low") -> None:
        self._flags.append(
            {"subStep": sub_step, "code": code, "message": message, "severity": severity}
        )

    @property
    def flags(self) -> List[Dict[str, str]]:
        return list(self._flags)

    @property
    def confidence(self) -> str:
        return "auto-low" if any(f["severity"] == "low" for f in self._flags) else "auto-high"


class _Projection:
    """lng/lat <-> local (east, north) meters about a fixed anchor."""

    def __init__(self, anchor_lng: float, anchor_lat: float) -> None:
        self.lng = anchor_lng
        self.lat = anchor_lat
        self.per_lng, self.per_lat = meters_per_degree(anchor_lat)

    def to_meters(self, points: Sequence[Sequence[float]]) -> g.Ring:
        return [((p[0] - self.lng) * self.per_lng, (p[1] - self.lat) * self.per_lat) for p in points]

    def to_lng_lat(self, point: g.Point) -> Tuple[float, float]:
        return (self.lng + point[0] / self.per_lng, self.lat + point[1] / self.per_lat)


# --- mesh ------------------------------------------------------------------

# (horizontal-a, horizontal-b, up) vertex indices, and the sign applied to the
# second horizontal axis so that (east, north, up) stays right-handed.
_AXES = {"y": (0, 2, 1, -1.0), "z": (0, 1, 2, 1.0)}


def mesh_base_outline(vertices, up_axis: str = "y", slab_fraction: float = 0.12,
                      min_base_coverage: float = 0.25) -> Dict[str, Any]:
    """Convex outline of the mesh base, plus its vertical extent.

    The base, not the silhouette from above: step 08 scores this against the OSM
    *footprint*, which is where the building meets the ground, and a roof
    overhang or a spire would inflate a top-down outline and bias both the IoU
    search and the scale fit.

    The slab widens when its hull is degenerate or covers a tiny fraction of the
    mesh's overall silhouette -- photogrammetry output often has a sparse, noisy
    lowest layer. The test is on hull *area*, not vertex count, so a clean
    low-poly base is accepted as-is rather than widened into meaninglessness.
    """
    if up_axis not in _AXES:
        raise PlacementInputError(f"upAxis must be 'y' or 'z', got {up_axis!r}")
    ia, ib, iu, sign = _AXES[up_axis]

    ups = [float(v[iu]) for v in vertices]
    min_up, max_up = min(ups), max(ups)
    height = max_up - min_up

    all_points = [(float(v[ia]), sign * float(v[ib])) for v in vertices]
    silhouette = g.area(g.convex_hull(all_points))

    outline: g.Ring = []
    frac = slab_fraction
    for _ in range(6):
        cutoff = min_up + max(height * frac, 1e-9)
        slab = [
            (float(v[ia]), sign * float(v[ib]))
            for v in vertices
            if float(v[iu]) <= cutoff
        ]
        outline = g.convex_hull(slab)
        covered = (g.area(outline) / silhouette) if silhouette > 0 else 0.0
        if len(outline) >= 3 and covered >= min_base_coverage:
            break
        if frac >= 1.0:
            break
        frac = min(1.0, frac * 2)

    if len(outline) < 3:
        outline = g.convex_hull(all_points)
        frac = 1.0

    b = g.bounds(outline)
    return {
        "outline": outline,
        "slabFraction": frac,
        "baseOffset": min_up,
        "heightUnits": height,
        "width": b["width"],
        "depth": b["depth"],
        "upAxis": up_axis,
        "vertexCount": len(outline),
    }


def _load_mesh_vertices(mesh_input: Dict[str, Any]):
    """Vertices from a .glb/.obj path, bytes, or an already-extracted outline."""
    import io

    import trimesh

    data = mesh_input.get("bytes")
    path = mesh_input.get("path")

    if data is not None:
        ext = (path or mesh_input.get("meshUrl") or "mesh.glb").rsplit(".", 1)[-1].lower()
        loaded = trimesh.load(io.BytesIO(data), file_type=ext, force="mesh")
    elif path:
        try:
            loaded = trimesh.load(path, force="mesh")
        except Exception as exc:  # missing file, unreadable format
            raise PlacementInputError(f'Could not read mesh at "{path}": {exc}') from exc
    else:
        raise PlacementInputError(
            "Mesh input needs one of: bytes, path, or a precomputed baseOutline."
        )

    if not hasattr(loaded, "vertices") or len(loaded.vertices) == 0:
        raise PlacementInputError("Mesh contains no vertices.")
    return loaded.vertices


def _resolve_mesh(mesh_input: Dict[str, Any]) -> Dict[str, Any]:
    up_axis = mesh_input.get("upAxis", "y")

    precomputed = mesh_input.get("baseOutline")
    if precomputed and len(precomputed) >= 3:
        outline = [(float(p[0]), float(p[1])) for p in precomputed]
        b = g.bounds(outline)
        return {
            "outline": outline,
            "slabFraction": 0.0,
            "baseOffset": float(mesh_input.get("baseOffset", 0.0)),
            "heightUnits": float(mesh_input.get("heightUnits", 0.0)),
            "width": b["width"],
            "depth": b["depth"],
            "upAxis": up_axis,
            "vertexCount": len(outline),
        }

    return mesh_base_outline(_load_mesh_vertices(mesh_input), up_axis=up_axis)


# --- fit -------------------------------------------------------------------


def _fit_scale(mesh_outline: g.Ring, footprint_ring: g.Ring, heading: float) -> Dict[str, float]:
    """Fit the mesh to the footprint *in the mesh's own frame*.

    This matters more than it looks. deck.gl applies the transform as
    translate(rotate(scale(model))) -- scale acts on model-space axes, before any
    rotation -- so the axes a non-uniform scale stretches are the mesh's own, not
    compass east/north. Fitting against the footprint's east/north bounding box
    would compute the stretch in the wrong frame entirely.

    It also fixes a real problem with the buildings this runs on: VT's campus is
    laid out diagonally, and measured footprints cluster around bearings of 45
    and 136 degrees, where an axis-aligned box can be nearly three times the
    building's actual area.
    """
    target = g.bounds(g.rotate_ring(footprint_ring, -heading))
    mesh = g.bounds(mesh_outline)

    mesh_w = max(mesh["width"], 1e-9)
    mesh_d = max(mesh["depth"], 1e-9)
    sx = target["width"] / mesh_w
    sy = target["depth"] / mesh_d

    # Spec 08 defaults to "a single uniform scale factor that fits the mesh to
    # both". The smaller of the two fits inside both; the larger, or a mean,
    # would overhang the footprint on one axis and cost IoU.
    return {
        "uniform": min(sx, sy),
        "perAxis": (sx, sy),
        "meshWidth": mesh_w,
        "meshDepth": mesh_d,
        "targetWidth": target["width"],
        "targetDepth": target["depth"],
    }


def _place(mesh_outline: g.Ring, heading: float, scale, target_centroid: g.Point):
    """Place an outline the way the renderer will: scale in model space, rotate
    about the model origin, then translate the origin onto the footprint."""
    transformed = g.rotate_ring(g.scale_ring(mesh_outline, scale), heading)
    c = g.centroid(transformed)
    offset = (target_centroid[0] - c[0], target_centroid[1] - c[1])
    return g.translate_ring(transformed, offset), offset


def _refine_offset(transformed: g.Ring, footprint_ring: g.Ring, footprint_area: float,
                   seed: g.Point, initial_step: float) -> Tuple[g.Point, float]:
    """Nudge to the offset that actually maximises IoU.

    Centring the mesh's centroid on the footprint's is the right starting point,
    but the mesh outline is convex while a real OSM footprint often is not, and
    the centroid of an L-shaped building is not where its hull's centroid sits.
    On the measured VT footprints that mismatch costs a couple of meters of
    position, which is plainly visible on a map.
    """

    def score(offset: g.Point) -> float:
        placed = g.translate_ring(transformed, offset)
        inter = g.intersection_area(footprint_ring, placed)
        union = g.area(placed) + footprint_area - inter
        return inter / union if union > 0 else 0.0

    directions = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))
    best, best_score, step = seed, score(seed), initial_step

    # 0.05 m floor: finer than that is below the accuracy of the OSM polygon
    # itself, so it would be precision without meaning.
    while step > 0.05:
        improved = False
        for dx, dy in directions:
            cand = (best[0] + dx * step, best[1] + dy * step)
            cand_score = score(cand)
            if cand_score > best_score + 1e-9:
                best, best_score, improved = cand, cand_score, True
        if not improved:
            step /= 2
    return best, best_score


# --- the transform ---------------------------------------------------------


def _ring_lng_lat(polygon: Dict[str, Any]) -> List[List[float]]:
    geom = polygon.get("geometry") or []
    if not geom:
        raise PlacementInputError("Footprint polygon has no geometry.")
    # Tolerate [{lat, lng}] as well as GeoJSON [[lng, lat]].
    if isinstance(geom[0], dict):
        return [[float(p["lng"]), float(p["lat"])] for p in geom]
    return [[float(p[0]), float(p[1])] for p in geom]


def compute_placement_transform(
    footprint: Dict[str, Any],
    mesh: Dict[str, Any],
    options: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    opts = {**DEFAULTS, **(options or {})}
    ledger = _Ledger()

    polygon = footprint.get("polygon") or footprint.get("selected")
    if not polygon:
        raise PlacementInputError('Needs "footprint.polygon" (or step 02\'s "selected").')

    raw = _ring_lng_lat(polygon)
    if len(g.open_ring([(p[0], p[1]) for p in raw])) < 3:
        raise PlacementInputError(
            f"Footprint polygon needs at least 3 distinct vertices, got {len(raw)}."
        )

    anchor = polygon_centroid([(p[0], p[1]) for p in raw])
    proj = _Projection(anchor[0], anchor[1])

    footprint_ring = g.open_ring(proj.to_meters(raw))
    footprint_centroid = g.centroid(footprint_ring)
    footprint_bounds = g.bounds(footprint_ring)
    footprint_area = g.area(footprint_ring)

    if footprint_area < 1:
        raise PlacementInputError(
            f"Footprint polygon area is {footprint_area:.2f} m2 -- too small to place against."
        )

    # Step 02's confidence propagates. It is a distinct uncertainty source from
    # anything decided here, and step 09 needs to tell them apart.
    if footprint.get("confidence") in ("low", "auto-low"):
        ledger.flag(
            "footprint",
            "footprint-match-low",
            "Step 02 reported a low-confidence footprint match; the polygon itself may be "
            "the wrong building.",
        )

    # --- cross-check step 02's derived numbers ---------------------------
    # Recomputed here rather than trusted: a disagreement is worth surfacing,
    # not silently working around.
    computed_axis = g.min_area_rectangle(footprint_ring)
    mismatches: List[Dict[str, float]] = []

    def check(field: str, reported, computed: float) -> None:
        if reported is None:
            return
        if abs(float(reported) - computed) > max(1.0, computed * 0.10):
            mismatches.append({"field": field, "reported": float(reported), "computed": computed})

    check("footprintWidthMeters", polygon.get("footprintWidthMeters"), computed_axis["length"])
    check("footprintDepthMeters", polygon.get("footprintDepthMeters"), computed_axis["width"])

    reported_rotation = polygon.get("rotationDegrees")
    if reported_rotation is not None:
        delta = abs(float(reported_rotation) - computed_axis["angleDegrees"]) % 180.0
        if min(delta, 180.0 - delta) > 15.0:
            mismatches.append(
                {
                    "field": "rotationDegrees",
                    "reported": float(reported_rotation),
                    "computed": computed_axis["angleDegrees"],
                }
            )

    if mismatches:
        ledger.flag(
            "footprint",
            "derived-values-disagree",
            "Step 02's derived values disagree with this polygon: "
            + "; ".join(
                f"{m['field']} reported {m['reported']:.2f}, computed {m['computed']:.2f}"
                for m in mismatches
            )
            + ". Placement used the values computed from the polygon.",
        )

    # --- mesh -------------------------------------------------------------
    mesh_info = _resolve_mesh(mesh)
    mesh_outline = mesh_info["outline"]
    if len(mesh_outline) < 3 or g.area(mesh_outline) <= 0:
        raise PlacementInputError(
            "Mesh base outline is degenerate -- step 07 may not have produced a usable base."
        )

    # --- rotation search --------------------------------------------------
    # Spec 08 generates candidates from the footprint's longest-edge bearing
    # "plus that angle +/- 0/90/180/270". Applied literally that assumes the mesh
    # arrives with its own long axis pointing north. Step 07 squares its output
    # up with X/Z, which gets close, but the candidate heading cancels whatever
    # orientation the mesh actually has:
    #
    #     heading = footprintAxis - meshAxis + offset
    #
    # That reduces to the spec's formula when the mesh axis is 0, and keeps the
    # four candidates exactly 90 degrees apart -- which is what step 09's "try
    # these 4 alignments" buttons need.
    footprint_axis = computed_axis["angleDegrees"]
    mesh_axis = g.min_area_rectangle(mesh_outline)["angleDegrees"]

    candidates: List[Dict[str, Any]] = []
    for offset in ROTATION_OFFSETS:
        heading = g.normalize_degrees(footprint_axis - mesh_axis + offset)
        fit = _fit_scale(mesh_outline, footprint_ring, heading)
        placed, _ = _place(mesh_outline, heading, fit["uniform"], footprint_centroid)

        inter = g.intersection_area(footprint_ring, placed)
        union = g.area(placed) + footprint_area - inter

        candidates.append(
            {
                "offsetDegrees": offset,
                # Output in the renderer's yaw convention, not the internal heading.
                "rotationDegrees": g.normalize_degrees(-heading),
                "headingDegrees": heading,
                "iou": (inter / union) if union > 0 else 0.0,
                "intersectionAreaSqM": inter,
                "scale": fit["uniform"],
                "coverage": [
                    fit["uniform"] * fit["meshWidth"] / max(fit["targetWidth"], 1e-9),
                    fit["uniform"] * fit["meshDepth"] / max(fit["targetDepth"], 1e-9),
                ],
            }
        )

    ranked = sorted(candidates, key=lambda c: c["iou"], reverse=True)
    winner = ranked[0]

    # The 180-degree flip is a special case, not a rival. A footprint is very
    # nearly centrosymmetric, so turning a mesh end-for-end barely changes its
    # IoU -- measured across the real fixtures, 44% of buildings had their top
    # two candidates within the ambiguity margin and every one of them was a
    # pure 0-vs-180 pair. Flagging those marks half of all placements for review
    # over a distinction footprint IoU cannot make in principle. Ambiguity is
    # judged against the best geometrically distinguishable alternative instead;
    # the flip margin is reported so step 09 can still offer "turn it around".
    flip = next((c for c in ranked if abs(c["offsetDegrees"] - winner["offsetDegrees"]) == 180), None)
    runner_up = next(
        (c for c in ranked if c is not winner and abs(c["offsetDegrees"] - winner["offsetDegrees"]) != 180),
        None,
    )
    flip_margin = (winner["iou"] - flip["iou"]) if flip else None

    if runner_up is not None and winner["iou"] - runner_up["iou"] < opts["rotationAmbiguityMargin"]:
        ledger.flag(
            "rotation",
            "rotation-ambiguous",
            f"Top two distinguishable rotations are within "
            f"{winner['iou'] - runner_up['iou']:.3f} IoU "
            f"({winner['rotationDegrees']:.1f} vs {runner_up['rotationDegrees']:.1f} yaw) -- the mesh "
            "may belong across the footprint rather than along it, and IoU cannot separate the two.",
        )

    # A mesh base outline is convex; a real OSM footprint frequently is not. So
    # the highest IoU any convex outline could score against this polygon is the
    # polygon against its own hull -- 0.48 for Campbell Hall, 0.98 for Sandy
    # Hall. One absolute threshold would flag a perfect placement on the concave
    # buildings and wave a mediocre one through on the simple ones.
    max_achievable_iou = g.iou(footprint_ring, g.convex_hull(footprint_ring))

    # --- scale ------------------------------------------------------------
    heading = winner["headingDegrees"]
    fit = _fit_scale(mesh_outline, footprint_ring, heading)
    worst_coverage = min(winner["coverage"])

    scale_mode = "uniform"
    horizontal = (fit["uniform"], fit["uniform"])

    if worst_coverage < opts["undersizeThreshold"]:
        # Uniform scaling leaves the mesh badly undersized on one axis, so fall
        # back to independent width/depth stretching. Height stays on the
        # uniform factor: spec 08 authorises stretching width and depth, and a
        # building that grows taller because its plan is the wrong aspect ratio
        # would look plainly wrong.
        scale_mode = "non-uniform"
        horizontal = fit["perAxis"]
        stretch = max(horizontal) / max(min(horizontal), 1e-9)
        extreme = stretch > opts["extremeStretchRatio"]
        ledger.flag(
            "scale",
            "non-uniform-fallback",
            f"Uniform scaling covered only {worst_coverage * 100:.0f}% of the footprint on one axis "
            f"(threshold {opts['undersizeThreshold'] * 100:.0f}%); fell back to independent "
            f"width/depth scaling ({fit['perAxis'][0]:.3f} x {fit['perAxis'][1]:.3f}, "
            f"{stretch:.2f}x aspect distortion). "
            + (
                "That is far enough out of proportion to be worth a human look."
                if extreme
                else "A mesh reconstructed from a single photograph routinely under-guesses "
                "depth, so this is the expected correction rather than a fault."
            ),
            severity="low" if extreme else "info",
        )

    fit_ratio = max(fit["uniform"], 1.0 / max(fit["uniform"], 1e-9))
    if fit_ratio > IMPLAUSIBLE_SCALE_RATIO:
        ledger.flag(
            "mesh",
            "implausible-scale",
            f"Fitting the mesh needed a {fit['uniform']:.3f}x scale -- off by more than "
            f"{IMPLAUSIBLE_SCALE_RATIO}x. This looks like a units problem in step 07's "
            "normalization, not a scale-fitting result.",
        )

    transformed = g.rotate_ring(g.scale_ring(mesh_outline, horizontal), heading)
    tc = g.centroid(transformed)
    seed = (footprint_centroid[0] - tc[0], footprint_centroid[1] - tc[1])
    offset, final_iou = _refine_offset(
        transformed,
        footprint_ring,
        footprint_area,
        seed,
        max(footprint_bounds["width"], footprint_bounds["depth"]) * 0.1,
    )
    placed_outline = g.translate_ring(transformed, offset)
    placed_area = g.area(placed_outline)

    fit_quality = (final_iou / max_achievable_iou) if max_achievable_iou > 0 else 0.0
    if fit_quality < opts["minFitQuality"]:
        ledger.flag(
            "rotation",
            "low-iou",
            f"Best placement reached IoU {final_iou:.3f} against a ceiling of "
            f"{max_achievable_iou:.3f} for this footprint -- {fit_quality * 100:.0f}% of achievable, "
            f"below the {opts['minFitQuality'] * 100:.0f}% threshold. The mesh outline and the OSM "
            "polygon may not describe the same building.",
        )

    # --- collision --------------------------------------------------------
    # Neighbours come from step 02's already-fetched result. No new Overpass call.
    target_id = polygon.get("osmId", polygon.get("id"))
    overlaps: List[Dict[str, Any]] = []
    neighbors_checked = 0

    for neighbor in footprint.get("neighbors") or []:
        n_id = neighbor.get("osmId", neighbor.get("id"))
        if target_id is not None and n_id is not None and str(n_id) == str(target_id):
            continue
        try:
            n_ring = g.open_ring(proj.to_meters(_ring_lng_lat(neighbor)))
        except PlacementInputError:
            continue
        if len(n_ring) < 3:
            continue
        # Without ids, exclude anything that is essentially the target itself.
        if (target_id is None or n_id is None) and g.iou(n_ring, g.convex_hull(footprint_ring)) > 0.9:
            continue

        neighbors_checked += 1

        # Spec 08 asks for a bounding-box overlap test. Kept as the cheap gate --
        # but an axis-aligned box is a poor stand-in for a building on this
        # campus, where footprints sit at roughly 45 degrees to the compass and
        # their boxes overlap while the buildings are metres apart. A box hit is
        # confirmed against the actual polygons before it counts.
        if g.bbox_overlap_area(placed_outline, n_ring) <= 0:
            continue
        overlap = g.intersection_area(n_ring, placed_outline)
        if overlap <= 0:
            continue

        n_area = max(g.area(n_ring), 1e-9)
        mesh_area = max(placed_area, 1e-9)
        # The worse of the two ratios counts. Measured against the mesh alone, a
        # large building placed over a small neighbour covers it completely
        # while using a few percent of its own footprint, and would slip under
        # any mesh-relative threshold.
        overlaps.append(
            {
                "neighborId": n_id,
                "overlapAreaSqM": overlap,
                "overlapRatio": max(overlap / mesh_area, overlap / n_area),
                "overlapRatioOfMesh": overlap / mesh_area,
                "overlapRatioOfNeighbor": overlap / n_area,
            }
        )

    overlaps.sort(key=lambda o: o["overlapRatio"], reverse=True)
    worst_overlap = overlaps[0]["overlapRatio"] if overlaps else 0.0

    if worst_overlap > opts["collisionThreshold"]:
        ledger.flag(
            "collision",
            "neighbor-overlap",
            f"Placed mesh overlaps neighbouring footprint "
            f"{overlaps[0]['neighborId'] if overlaps[0]['neighborId'] is not None else '(unnamed)'} "
            f"by {worst_overlap * 100:.0f}% (threshold {opts['collisionThreshold'] * 100:.0f}%).",
        )

    # --- ground alignment -------------------------------------------------
    # Step 07 base-centres the pivot, so baseOffset should be ~0 and z ~0.
    # Computing it anyway means a mesh that was not quite base-centred still
    # lands on the ground instead of floating or sinking.
    vertical_scale = horizontal[0] if horizontal[0] == horizontal[1] else fit["uniform"]
    z = -mesh_info["baseOffset"] * vertical_scale

    if mesh_info["heightUnits"] > 0:
        base_fraction = abs(mesh_info["baseOffset"]) / mesh_info["heightUnits"]
        if base_fraction > 0.02:
            ledger.flag(
                "ground",
                "pivot-not-base-centred",
                f"Mesh base sits {mesh_info['baseOffset']:.3f} units from its own origin "
                f"({base_fraction * 100:.1f}% of its height). Step 07 should base-centre the pivot; "
                f"placement corrected for it with z = {z:.3f} m.",
                severity="info",
            )

    lng, lat = proj.to_lng_lat(offset)

    return {
        # --- the five fields spec 08 names -------------------------------
        "rotationDegrees": g.normalize_degrees(-heading),
        "scale": fit["uniform"],
        "position": [lat, lng, z],
        "confidence": ledger.confidence,
        "scoredRotationCandidates": ranked,
        # --- the working step 09 and step 12 need ------------------------
        "scaleMode": scale_mode,
        "scaleStretchRatio": max(horizontal) / max(min(horizontal), 1e-9),
        # Renderer order (X, Y, Z) in model space, for deck.gl's getScale.
        "scaleXYZ": [horizontal[0], vertical_scale, horizontal[1]],
        "flags": ledger.flags,
        "collision": {
            "neighborsChecked": neighbors_checked,
            "overlaps": overlaps,
            "worstOverlapRatio": worst_overlap,
        },
        "ground": {"meshBaseOffsetUnits": mesh_info["baseOffset"], "z": z},
        "diagnostics": {
            "iou": final_iou,
            "maxAchievableIou": max_achievable_iou,
            "fitQuality": fit_quality,
            "footprintAreaSqM": footprint_area,
            "placedMeshAreaSqM": placed_area,
            "footprintPrincipalAxisDegrees": footprint_axis,
            "footprintLengthMeters": computed_axis["length"],
            "footprintWidthMeters": computed_axis["width"],
            "meshPrincipalAxisDegrees": mesh_axis,
            "meshWidthUnits": mesh_info["width"],
            "meshDepthUnits": mesh_info["depth"],
            "meshHeightUnits": mesh_info["heightUnits"],
            "scaledHeightMeters": mesh_info["heightUnits"] * vertical_scale,
            "upAxis": mesh_info["upAxis"],
            "headingDegrees": heading,
            "rotationFlipMargin": flip_margin,
            "refinementShiftMeters": math.hypot(offset[0] - seed[0], offset[1] - seed[1]),
            "footprintDerivedMismatch": mismatches or None,
        },
    }
