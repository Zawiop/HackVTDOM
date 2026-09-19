"""Geodesy helpers for footprint analysis.

Degrees-to-meters conversion is latitude-dependent (see 02-footprint-overpass.md):
a degree of longitude shrinks toward the poles, so a fixed constant would skew
every width/depth measurement away from the equator.
"""

import math
from typing import List, Sequence, Tuple

# (lng, lat) throughout, matching GeoJSON order.
Point = Tuple[float, float]


def meters_per_degree(latitude: float) -> Tuple[float, float]:
    """Return (meters_per_degree_lng, meters_per_degree_lat) at this latitude."""
    phi = math.radians(latitude)
    per_lat = (
        111132.92
        - 559.82 * math.cos(2 * phi)
        + 1.175 * math.cos(4 * phi)
        - 0.0023 * math.cos(6 * phi)
    )
    per_lng = (
        111412.84 * math.cos(phi)
        - 93.5 * math.cos(3 * phi)
        + 0.118 * math.cos(5 * phi)
    )
    return per_lng, per_lat


def to_local_meters(points: Sequence[Point], origin: Point) -> List[Point]:
    """Project lng/lat degrees onto a local flat (east, north) meter plane.

    Accurate enough at building scale, where earth curvature is negligible.
    """
    per_lng, per_lat = meters_per_degree(origin[1])
    return [((p[0] - origin[0]) * per_lng, (p[1] - origin[1]) * per_lat) for p in points]


def polygon_centroid(points: Sequence[Point]) -> Point:
    """Area-weighted centroid, falling back to the vertex mean for degenerate rings."""
    ring = _open_ring(points)
    if len(ring) < 3:
        return (
            sum(p[0] for p in ring) / len(ring),
            sum(p[1] for p in ring) / len(ring),
        )

    # Shoelace terms are differences of products of the raw coordinates. At
    # lng ~-80 those products are ~1e3 while a building's area in square degrees
    # is ~1e-7, so summing them directly cancels away most of the mantissa and
    # shifts the centroid by a metre or more. Rebasing on the first vertex first
    # keeps every term at building scale.
    ox, oy = ring[0]
    local = [(x - ox, y - oy) for x, y in ring]

    twice_area = 0.0
    cx = 0.0
    cy = 0.0
    for i in range(len(local)):
        x0, y0 = local[i]
        x1, y1 = local[(i + 1) % len(local)]
        cross = x0 * y1 - x1 * y0
        twice_area += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross

    if abs(twice_area) < 1e-18:
        return (
            sum(p[0] for p in ring) / len(ring),
            sum(p[1] for p in ring) / len(ring),
        )

    area = twice_area / 2.0
    return (cx / (6.0 * area) + ox, cy / (6.0 * area) + oy)


def point_in_polygon(point: Point, polygon: Sequence[Point]) -> bool:
    """Ray-casting containment test."""
    ring = _open_ring(polygon)
    if len(ring) < 3:
        return False

    x, y = point
    inside = False
    for i in range(len(ring)):
        x0, y0 = ring[i]
        x1, y1 = ring[(i + 1) % len(ring)]
        if (y0 > y) != (y1 > y):
            t = (y - y0) / (y1 - y0)
            if x < x0 + t * (x1 - x0):
                inside = not inside
    return inside


def distance_point_to_polygon_meters(point: Point, polygon: Sequence[Point]) -> float:
    """Zero if the point is inside, else the shortest distance to any edge."""
    if point_in_polygon(point, polygon):
        return 0.0

    ring = _open_ring(polygon)
    local = to_local_meters(ring, point)
    if len(local) == 1:
        return math.hypot(local[0][0], local[0][1])

    best = float("inf")
    for i in range(len(local)):
        a = local[i]
        b = local[(i + 1) % len(local)]
        best = min(best, _point_segment_distance((0.0, 0.0), a, b))
    return best


def longest_edge_bearing_degrees(polygon: Sequence[Point]) -> float:
    """Compass bearing (0-180, from north, clockwise) of the polygon's longest edge.

    Collapsed to a half-circle because a building edge has no front or back: a
    wall bearing 200 degrees is the same wall as one bearing 20.
    """
    ring = _open_ring(polygon)
    if len(ring) < 2:
        return 0.0

    origin = polygon_centroid(ring)
    local = to_local_meters(ring, origin)

    best_length = -1.0
    best_bearing = 0.0
    for i in range(len(local)):
        ax, ay = local[i]
        bx, by = local[(i + 1) % len(local)]
        d_east = bx - ax
        d_north = by - ay
        length = math.hypot(d_east, d_north)
        if length > best_length:
            best_length = length
            best_bearing = math.degrees(math.atan2(d_east, d_north)) % 180.0
    return best_bearing


def oriented_extents_meters(
    polygon: Sequence[Point], bearing_degrees: float
) -> Tuple[float, float]:
    """Return (width, depth) in meters measured along / across `bearing_degrees`.

    An axis-aligned bounding box would overstate both dimensions for any building
    that is not square to the compass, which would then corrupt step 08's scale fit.
    """
    ring = _open_ring(polygon)
    if not ring:
        return 0.0, 0.0

    origin = polygon_centroid(ring)
    local = to_local_meters(ring, origin)

    theta = math.radians(bearing_degrees)
    # Unit vector along the bearing, and its perpendicular.
    along_e, along_n = math.sin(theta), math.cos(theta)
    across_e, across_n = math.cos(theta), -math.sin(theta)

    along = [p[0] * along_e + p[1] * along_n for p in local]
    across = [p[0] * across_e + p[1] * across_n for p in local]
    return max(along) - min(along), max(across) - min(across)


def polygon_area_sq_meters(points: Sequence[Point]) -> float:
    ring = _open_ring(points)
    if len(ring) < 3:
        return 0.0
    local = to_local_meters(ring, polygon_centroid(ring))
    twice_area = 0.0
    for i in range(len(local)):
        x0, y0 = local[i]
        x1, y1 = local[(i + 1) % len(local)]
        twice_area += x0 * y1 - x1 * y0
    return abs(twice_area) / 2.0


def bounding_box(points: Sequence[Point]) -> dict:
    lngs = [p[0] for p in points]
    lats = [p[1] for p in points]
    return {
        "minLng": min(lngs),
        "minLat": min(lats),
        "maxLng": max(lngs),
        "maxLat": max(lats),
    }


def _open_ring(points: Sequence[Point]) -> List[Point]:
    """Drop the repeated closing vertex that OSM ways carry."""
    ring = list(points)
    if len(ring) > 1 and ring[0] == ring[-1]:
        ring = ring[:-1]
    return ring


def _point_segment_distance(p: Point, a: Point, b: Point) -> float:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(p[0] - ax, p[1] - ay)
    t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))
