"""Step 02 — coordinate to real building polygon."""

import logging
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException

from ..config import get_settings
from ..models.contracts import FootprintCandidate, FootprintRequest, FootprintResult
from ..services import cache, geo_math, overpass

logger = logging.getLogger(__name__)

router = APIRouter(tags=["footprint"])

# Two candidates whose distances differ by less than this are "equally close",
# which 02-footprint-overpass.md says must never be resolved automatically.
AMBIGUITY_TOLERANCE_METERS = 5.0


@router.post("/footprint", response_model=FootprintResult)
async def footprint(request: FootprintRequest):
    settings = get_settings()
    match_radius = request.radiusMeters or settings.overpass_match_radius_meters
    # One wide query serves both the match and the neighbor set steps 08/10 reuse.
    neighbor_radius = max(settings.overpass_neighbor_radius_meters, match_radius)

    cached = cache.get(request.lat, request.lng, neighbor_radius)
    if cached is not None:
        elements, source = cached
        was_cached = True
    else:
        try:
            elements, source = await overpass.fetch_buildings(
                request.lat, request.lng, neighbor_radius
            )
        except overpass.OverpassError as exc:
            logger.warning("Overpass failed at %s,%s: %s", request.lat, request.lng, exc)
            raise HTTPException(
                status_code=502,
                detail="Building footprint service unavailable. Try again in a moment.",
            ) from exc
        cache.put(request.lat, request.lng, neighbor_radius, (elements, source))
        was_cached = False

    query_point = (request.lng, request.lat)
    parsed = [c for c in (_to_candidate(e, query_point) for e in elements) if c is not None]
    parsed.sort(key=lambda c: c.distanceMeters)

    candidates = [c for c in parsed if c.distanceMeters <= match_radius]
    neighbors = [c for c in parsed if c.distanceMeters > match_radius]

    selected, confidence, reason = _resolve(candidates, query_point)

    return FootprintResult(
        confidence=confidence,
        reason=reason,
        selected=selected,
        candidates=candidates,
        neighbors=neighbors,
        queryPoint=[request.lng, request.lat],
        matchRadiusMeters=match_radius,
        neighborRadiusMeters=neighbor_radius,
        cached=was_cached,
        source=source,
    )


def _resolve(
    candidates: List[FootprintCandidate], query_point: Tuple[float, float]
) -> Tuple[Optional[FootprintCandidate], str, str]:
    """Pick a footprint, or refuse to and hand every option to step 09."""
    if not candidates:
        return None, "auto-low", "No building footprint found at this location."

    containing = [
        c for c in candidates if geo_math.point_in_polygon(query_point, _ring(c))
    ]
    if len(containing) == 1:
        return containing[0], "auto-high", "Point falls inside exactly one building footprint."
    if len(containing) > 1:
        return (
            None,
            "auto-low",
            f"Point falls inside {len(containing)} overlapping footprints — pick the right one.",
        )

    nearest = candidates[0]
    if len(candidates) == 1:
        return (
            nearest,
            "auto-high",
            f"One building within {nearest.distanceMeters:.1f} m of the point.",
        )

    runner_up = candidates[1]
    if runner_up.distanceMeters - nearest.distanceMeters < AMBIGUITY_TOLERANCE_METERS:
        return (
            None,
            "auto-low",
            f"{len(candidates)} buildings are within {AMBIGUITY_TOLERANCE_METERS:.0f} m "
            "of each other — pick the right one.",
        )

    return (
        nearest,
        "auto-high",
        f"Nearest building is {runner_up.distanceMeters - nearest.distanceMeters:.1f} m "
        "clear of the next candidate.",
    )


def _ring(candidate: FootprintCandidate) -> List[Tuple[float, float]]:
    return [(p[0], p[1]) for p in candidate.geometry]


def _nodes_to_ring(geometry: Any) -> List[Tuple[float, float]]:
    if not isinstance(geometry, list):
        return []
    ring: List[Tuple[float, float]] = []
    for node in geometry:
        try:
            ring.append((float(node["lon"]), float(node["lat"])))
        except (KeyError, TypeError, ValueError):
            return []
    return ring


def _stitch_outer_ring(segments: List[List[Tuple[float, float]]]) -> List[Tuple[float, float]]:
    """Join a multipolygon's outer member ways into a single ring.

    Overpass returns a relation's outer boundary as separate member ways that
    share end nodes rather than one closed ring. Where a relation has several
    disjoint outer rings (a building complex), the largest one wins.
    """
    remaining = [list(s) for s in segments if len(s) >= 2]
    rings: List[List[Tuple[float, float]]] = []

    while remaining:
        ring = remaining.pop(0)
        joined = True
        while joined and remaining:
            joined = False
            for i, seg in enumerate(remaining):
                if ring[-1] == seg[0]:
                    ring.extend(seg[1:])
                elif ring[-1] == seg[-1]:
                    ring.extend(seg[-2::-1])
                elif ring[0] == seg[-1]:
                    ring = seg[:-1] + ring
                elif ring[0] == seg[0]:
                    ring = seg[:0:-1] + ring
                else:
                    continue
                remaining.pop(i)
                joined = True
                break
        rings.append(ring)

    if not rings:
        return []
    return max(rings, key=geo_math.polygon_area_sq_meters)


def _element_ring(element: Dict[str, Any]) -> List[Tuple[float, float]]:
    if element.get("type") == "relation":
        outer = [
            _nodes_to_ring(m.get("geometry"))
            for m in element.get("members") or []
            if isinstance(m, dict) and m.get("role") in ("outer", "")
        ]
        return _stitch_outer_ring([s for s in outer if len(s) >= 2])
    return _nodes_to_ring(element.get("geometry"))


def _to_candidate(
    element: Dict[str, Any], query_point: Tuple[float, float]
) -> Optional[FootprintCandidate]:
    ring = _element_ring(element)
    if len(ring) < 3:
        return None

    bearing = geo_math.longest_edge_bearing_degrees(ring)
    width, depth = geo_math.oriented_extents_meters(ring, bearing)
    centroid = geo_math.polygon_centroid(ring)

    raw_tags = element.get("tags") or {}
    tags = {str(k): str(v) for k, v in raw_tags.items()}

    return FootprintCandidate(
        osmId=int(element.get("id", 0)),
        osmType=str(element.get("type", "way")),
        tags=tags,
        geometry=[[p[0], p[1]] for p in ring],
        centroid=[centroid[0], centroid[1]],
        distanceMeters=round(geo_math.distance_point_to_polygon_meters(query_point, ring), 2),
        footprintWidthMeters=round(width, 2),
        footprintDepthMeters=round(depth, 2),
        rotationDegrees=round(bearing, 2),
        boundingBox=geo_math.bounding_box(ring),
    )
