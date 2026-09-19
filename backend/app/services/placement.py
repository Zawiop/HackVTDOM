"""Step 08 — rotation, scale, collision and ground alignment.

Pure computation. Everything it needs already exists: the chosen polygon and
neighbour footprints from step 02, and the mesh's normalized extents from step 07.

The mesh footprint is modelled as the rectangle of its normalized width x depth
rather than its true base outline. TripoSR-class meshes are single-image
reconstructions with noisy, blobby bases, so a rectangle is both more stable and
enough to rank four rotations against a real polygon. The consequence is spelled
out in `rotation_note` below: a rectangle is symmetric under 180 degrees, so the
IoU search cannot tell a facade from its back. That distinction is left to the
human in step 09, which is where the spec already puts it.
"""

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import geo_math

# A rectangle can never cover an L-shaped or bridged building completely, so the
# achievable IoU is capped by how rectangular the footprint is. The test is
# therefore relative: the best rotation must reach this fraction of that ceiling.
MIN_FIT_QUALITY = 0.80
# Below this, the footprint is so un-rectangular that a rectangle says nothing
# useful about orientation and a human should look.
MIN_RECTANGULARITY = 0.35
# Two orientations this close are a coin flip — a near-square building.
ROTATION_AMBIGUITY_MARGIN = 0.05
# Uniform scaling leaving the mesh more than this much short on the free axis
# is "badly undersized" (08-placement-transform.md asks for a concrete number).
MAX_UNIFORM_SHORTFALL = 0.30
# Share of the mesh footprint that may sit on a neighbour before it is a problem.
MAX_NEIGHBOR_OVERLAP = 0.10

ROTATION_OFFSETS = (0.0, 90.0, 180.0, 270.0)


def compute_placement(
    polygon_lnglat: Sequence[Tuple[float, float]],
    base_bearing_degrees: float,
    mesh_width_meters: float,
    mesh_depth_meters: float,
    neighbors_lnglat: Sequence[Sequence[Tuple[float, float]]] = (),
    footprint_confidence: str = "auto-high",
) -> Dict[str, Any]:
    if mesh_width_meters <= 0 or mesh_depth_meters <= 0:
        raise ValueError("mesh extents must be positive metres")

    centroid = geo_math.polygon_centroid(polygon_lnglat)
    local_polygon = geo_math.to_local_meters(polygon_lnglat, centroid)
    origin = (0.0, 0.0)

    candidates = [
        _score_rotation(
            local_polygon, polygon_lnglat, origin, base_bearing_degrees + offset,
            offset, mesh_width_meters, mesh_depth_meters,
        )
        for offset in ROTATION_OFFSETS
    ]
    best = max(candidates, key=lambda c: c["iou"])

    warnings: List[str] = []
    checks: Dict[str, Dict[str, Any]] = {}

    checks["footprintMatch"] = {
        "ok": footprint_confidence != "auto-low",
        "detail": (
            "Step 02 flagged the footprint match as ambiguous."
            if footprint_confidence == "auto-low"
            else "Step 02 matched a single footprint."
        ),
    }

    shape_ratio = rectangularity(local_polygon, best["rotationDegrees"])
    checks["rotation"] = _check_rotation(candidates, best, shape_ratio, warnings)
    scale, scale_xyz, checks["scale"] = _check_scale(
        local_polygon, best["rotationDegrees"], mesh_width_meters, mesh_depth_meters, warnings
    )

    placed = geo_math.oriented_rectangle(
        origin, mesh_width_meters * scale, mesh_depth_meters * scale, best["rotationDegrees"]
    )
    checks["collision"] = _check_collision(placed, neighbors_lnglat, centroid, warnings)

    # Step 07 guarantees a base-center pivot at y=0, so ground level is z=0.
    # One flagged sub-check is never overwritten by a later clean one.
    checks["groundAlignment"] = {
        "ok": True,
        "detail": "Mesh pivot is base-center (step 07), so z=0 sits on the ground.",
    }

    confidence = "auto-high" if all(c["ok"] for c in checks.values()) else "auto-low"

    return {
        "rotationDegrees": round(best["rotationDegrees"], 2),
        "scale": round(scale, 4),
        "scaleXYZ": scale_xyz,
        "position": [round(centroid[1], 7), round(centroid[0], 7), 0.0],
        "confidence": confidence,
        "scoredRotationCandidates": candidates,
        "checks": checks,
        "rectangularity": round(shape_ratio, 4),
        "warnings": warnings,
        "rotation_note": (
            "The mesh footprint is approximated by its normalized width x depth "
            "rectangle, which is symmetric under 180 degrees — the 0/180 and "
            "90/270 candidates therefore score identically. Facade direction is a "
            "step 09 decision."
        ),
    }


def _score_rotation(
    local_polygon: List[Tuple[float, float]],
    polygon_lnglat: Sequence[Tuple[float, float]],
    origin: Tuple[float, float],
    bearing: float,
    offset: float,
    mesh_w: float,
    mesh_d: float,
) -> Dict[str, float]:
    bearing %= 360.0
    scale = _uniform_scale(local_polygon, bearing, mesh_w, mesh_d)[0]
    rect = geo_math.oriented_rectangle(origin, mesh_w * scale, mesh_d * scale, bearing)
    return {
        "rotationDegrees": round(bearing, 2),
        "offsetDegrees": offset,
        "iou": round(geo_math.intersection_over_union(local_polygon, rect), 4),
        "scale": round(scale, 4),
    }


def _uniform_scale(
    local_polygon: Sequence[Tuple[float, float]], bearing: float, mesh_w: float, mesh_d: float
) -> Tuple[float, float, float]:
    """Return (uniform, along_fit, across_fit) scale factors for this bearing."""
    along, across = geo_math.oriented_extents_2d(local_polygon, bearing)
    fit_along = along / mesh_w
    fit_across = across / mesh_d
    # min() keeps the mesh inside the real footprint, which also keeps the
    # collision check honest — an over-scaled mesh would invent overlaps.
    return min(fit_along, fit_across), fit_along, fit_across


def rectangularity(local_polygon: Sequence[Tuple[float, float]], bearing: float) -> float:
    """Polygon area as a share of its oriented bounding box. 1.0 is a perfect rectangle."""
    along, across = geo_math.oriented_extents_2d(local_polygon, bearing)
    box_area = along * across
    if box_area <= 0:
        return 0.0
    return geo_math.polygon_area_2d(local_polygon) / box_area


def _check_rotation(
    candidates: List[Dict[str, float]],
    best: Dict[str, float],
    shape_ratio: float,
    warnings: List[str],
) -> Dict[str, Any]:
    if shape_ratio < MIN_RECTANGULARITY:
        warnings.append(
            f"Footprint fills only {shape_ratio:.0%} of its bounding box — too irregular "
            "for a rectangle to orient reliably."
        )
        return {
            "ok": False,
            "detail": (
                f"Footprint is {shape_ratio:.0%} rectangular "
                f"(< {MIN_RECTANGULARITY:.0%}) — needs a human to confirm orientation."
            ),
        }

    quality = best["iou"] / shape_ratio if shape_ratio > 0 else 0.0
    if quality < MIN_FIT_QUALITY:
        warnings.append(
            f"Best rotation reaches IoU {best['iou']:.2f} against a ceiling of "
            f"{shape_ratio:.2f} for this shape."
        )
        return {
            "ok": False,
            "detail": (
                f"Best rotation only reaches {quality:.0%} of the achievable fit "
                f"(< {MIN_FIT_QUALITY:.0%})."
            ),
        }

    # A rectangle at b and b+180 is the same rectangle, so compare the two
    # genuinely distinct orientations instead of the raw top two.
    classes: Dict[float, float] = {}
    for c in candidates:
        key = round(c["rotationDegrees"] % 180.0, 2)
        classes[key] = max(classes.get(key, 0.0), c["iou"])
    scores = sorted(classes.values(), reverse=True)

    if len(scores) > 1 and scores[0] - scores[1] < ROTATION_AMBIGUITY_MARGIN:
        warnings.append(
            f"Footprint is near-square: the two orientations score {scores[0]:.2f} "
            f"and {scores[1]:.2f}."
        )
        return {
            "ok": False,
            "detail": "Two orientations fit equally well — needs a human to pick.",
        }

    return {
        "ok": True,
        "detail": (
            f"Best rotation fits at IoU {best['iou']:.2f} "
            f"({quality:.0%} of what this shape allows)."
        ),
    }


def _check_scale(
    local_polygon: Sequence[Tuple[float, float]],
    bearing: float,
    mesh_w: float,
    mesh_d: float,
    warnings: List[str],
) -> Tuple[float, Optional[List[float]], Dict[str, Any]]:
    uniform, fit_along, fit_across = _uniform_scale(local_polygon, bearing, mesh_w, mesh_d)
    larger = max(fit_along, fit_across)
    shortfall = 0.0 if larger <= 0 else 1.0 - (uniform / larger)

    if shortfall <= MAX_UNIFORM_SHORTFALL:
        return uniform, None, {
            "ok": True,
            "detail": f"Uniform scale {uniform:.3f} fits within {shortfall:.0%} on both axes.",
        }

    # Proportion-preserving is the stated preference, so the uniform factor stays
    # the one `scale` reports; the stretch is offered alongside it.
    warnings.append(
        f"Uniform scaling leaves the mesh {shortfall:.0%} short on one axis; "
        "scaleXYZ carries the non-uniform fit."
    )
    return uniform, [round(fit_along, 4), 1.0, round(fit_across, 4)], {
        "ok": False,
        "detail": (
            f"Mesh and footprint proportions disagree by {shortfall:.0%} "
            f"(> {MAX_UNIFORM_SHORTFALL:.0%}); uniform scale would look undersized."
        ),
    }


def _check_collision(
    placed_rect: Sequence[Tuple[float, float]],
    neighbors_lnglat: Sequence[Sequence[Tuple[float, float]]],
    centroid: Tuple[float, float],
    warnings: List[str],
) -> Dict[str, Any]:
    mesh_area = geo_math.polygon_area_2d(placed_rect)
    if mesh_area <= 0 or not neighbors_lnglat:
        return {"ok": True, "detail": "No neighbouring footprints to collide with."}

    # 08-placement-transform.md says bounding-box overlap. Axis-aligned boxes
    # around two diagonal buildings overlap heavily even when the buildings do
    # not touch — on the VT campus that flags almost everything. The placed mesh
    # is a convex rectangle, so the real intersection is one clip away and costs
    # nothing extra.
    worst = 0.0
    for neighbor in neighbors_lnglat:
        if len(neighbor) < 3:
            continue
        local = geo_math.to_local_meters(neighbor, centroid)
        overlap = geo_math.polygon_area_2d(geo_math.clip_polygon_convex(local, placed_rect))
        worst = max(worst, overlap / mesh_area)

    if worst > MAX_NEIGHBOR_OVERLAP:
        warnings.append(f"Placed mesh overlaps a neighbouring building by {worst:.0%}.")
        return {
            "ok": False,
            "detail": f"Overlaps a neighbour by {worst:.0%} (> {MAX_NEIGHBOR_OVERLAP:.0%}).",
        }
    return {"ok": True, "detail": f"Largest neighbour overlap is {worst:.0%}."}
