"""Planar geometry for the placement transform (08-placement-transform.md).

Everything here works in the local (east, north) meter plane that
`geo_math.to_local_meters` produces: pick an anchor lng/lat, convert nearby
points to meters, do ordinary 2D geometry, convert back. At building scale the
error from ignoring curvature is a few centimeters over a hundred meters.

Angle convention throughout is a **compass heading** — 0 = north, 90 = east,
increasing clockwise — matching `geo_math.longest_edge_bearing_degrees` and the
`rotationDegrees` the rest of the pipeline speaks. That is the opposite winding
to the usual math convention, so rotation is written out explicitly rather than
borrowed from a standard rotation matrix.
"""

from __future__ import annotations

import math
from typing import List, Sequence, Tuple

Point = Tuple[float, float]
Ring = List[Point]

_EPS = 1e-9


# --- ring basics -----------------------------------------------------------


def open_ring(ring: Sequence[Point]) -> Ring:
    """Drop a duplicated closing vertex. OSM ways arrive closed; the math wants open."""
    pts = list(ring)
    if len(pts) >= 2:
        fx, fy = pts[0]
        lx, ly = pts[-1]
        if abs(fx - lx) < _EPS and abs(fy - ly) < _EPS:
            return pts[:-1]
    return pts


def signed_area(ring: Sequence[Point]) -> float:
    """Shoelace area. Positive means counter-clockwise in (east, north) space."""
    pts = open_ring(ring)
    if len(pts) < 3:
        return 0.0
    total = 0.0
    for i, (x0, y0) in enumerate(pts):
        x1, y1 = pts[(i + 1) % len(pts)]
        total += x0 * y1 - x1 * y0
    return total / 2.0


def area(ring: Sequence[Point]) -> float:
    return abs(signed_area(ring))


def centroid(ring: Sequence[Point]) -> Point:
    """Area-weighted centroid, falling back to the vertex mean when degenerate."""
    pts = open_ring(ring)
    if not pts:
        return (0.0, 0.0)
    if len(pts) < 3:
        return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))

    cx = cy = twice_area = 0.0
    for i, (x0, y0) in enumerate(pts):
        x1, y1 = pts[(i + 1) % len(pts)]
        cross = x0 * y1 - x1 * y0
        twice_area += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross

    if abs(twice_area) < 1e-12:
        return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
    return (cx / (3.0 * twice_area), cy / (3.0 * twice_area))


def bounds(ring: Sequence[Point]) -> dict:
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return {
        "minX": min(xs),
        "minY": min(ys),
        "maxX": max(xs),
        "maxY": max(ys),
        "width": max(xs) - min(xs),
        "depth": max(ys) - min(ys),
    }


# --- transforms ------------------------------------------------------------


def rotate_ring(ring: Sequence[Point], heading_degrees: float, origin: Point = (0.0, 0.0)) -> Ring:
    """Rotate by a compass heading about `origin`.

    Turning a shape to heading t moves it clockwise by t in (east, north) space,
    so a feature at bearing b ends up at bearing b + t:

        e' =  e*cos(t) + n*sin(t)
        n' = -e*sin(t) + n*cos(t)
    """
    t = math.radians(heading_degrees)
    cos_t, sin_t = math.cos(t), math.sin(t)
    ox, oy = origin
    out: Ring = []
    for x, y in ring:
        dx, dy = x - ox, y - oy
        out.append((ox + dx * cos_t + dy * sin_t, oy - dx * sin_t + dy * cos_t))
    return out


def scale_ring(ring: Sequence[Point], scale, origin: Point = (0.0, 0.0)) -> Ring:
    sx, sy = (scale, scale) if isinstance(scale, (int, float)) else scale
    ox, oy = origin
    return [(ox + (x - ox) * sx, oy + (y - oy) * sy) for x, y in ring]


def translate_ring(ring: Sequence[Point], offset: Point) -> Ring:
    dx, dy = offset
    return [(x + dx, y + dy) for x, y in ring]


def normalize_degrees(deg: float) -> float:
    """Fold any angle into [0, 360)."""
    return deg % 360.0


# --- hull and principal axis ----------------------------------------------


def convex_hull(points: Sequence[Point]) -> Ring:
    """Andrew's monotone chain. Turns a cloud of mesh base vertices into an outline."""
    pts = sorted(set(points))
    if len(pts) < 3:
        return list(pts)

    def cross(o: Point, a: Point, b: Point) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    def half(seq: Sequence[Point]) -> Ring:
        out: Ring = []
        for p in seq:
            while len(out) >= 2 and cross(out[-2], out[-1], p) <= 0:
                out.pop()
            out.append(p)
        out.pop()
        return out

    hull = half(pts) + half(pts[::-1])
    return hull if len(hull) >= 3 else list(pts)


def min_area_rectangle(ring: Sequence[Point]) -> dict:
    """Smallest-area enclosing rectangle, by rotating calipers.

    This is the shape's principal axis, and it is used instead of the longest
    edge wherever an *orientation* is needed. Measured on the real VT
    footprints: the min-area-rectangle angle of a building and of its own convex
    hull agree to 0.000 degrees across every building checked, while their
    longest edges disagree by as much as 65 -- because a hull edge that bridges
    a concave notch is long but says nothing about how the building is oriented.

    Step 08 always compares a mesh's convex base outline against a
    possibly-concave OSM polygon, so that stability is the difference between a
    building landing square on its footprint and landing 29 m away.

    The minimum-area rectangle always has one side collinear with a hull edge,
    so testing each hull edge is exact rather than a search.
    """
    hull = open_ring(convex_hull(open_ring(ring)))
    if len(hull) < 3:
        b = bounds(ring)
        return {
            "angleDegrees": 0.0,
            "length": b["width"],
            "width": b["depth"],
            "area": b["width"] * b["depth"],
        }

    best = None
    for i, (ax, ay) in enumerate(hull):
        bx, by = hull[(i + 1) % len(hull)]
        dx, dy = bx - ax, by - ay
        if math.hypot(dx, dy) < _EPS:
            continue

        # Compass bearing of this edge. rotate_ring maps a feature at bearing b
        # to b + t, so aligning this edge with north takes MINUS its bearing.
        edge_heading = math.degrees(math.atan2(dx, dy))
        box = bounds(rotate_ring(hull, -edge_heading))
        box_area = box["width"] * box["depth"]

        if best is None or box_area < best["area"]:
            # The rotation put the edge along north, so the box's north extent
            # lies along it; whichever side is longer is the rectangle's length.
            long_along_north = box["depth"] >= box["width"]
            best = {
                "angleDegrees": normalize_degrees(
                    edge_heading if long_along_north else edge_heading + 90.0
                )
                % 180.0,
                "length": max(box["width"], box["depth"]),
                "width": min(box["width"], box["depth"]),
                "area": box_area,
            }

    if best is not None:
        return best
    b = bounds(ring)
    return {
        "angleDegrees": 0.0,
        "length": b["width"],
        "width": b["depth"],
        "area": b["width"] * b["depth"],
    }


# --- boolean overlap -------------------------------------------------------


def _counter_clockwise(ring: Sequence[Point]) -> Ring:
    pts = open_ring(ring)
    return pts if signed_area(pts) >= 0 else pts[::-1]


def is_convex(ring: Sequence[Point]) -> bool:
    pts = open_ring(ring)
    if len(pts) < 3:
        return False
    sign = 0
    for i in range(len(pts)):
        ax, ay = pts[i]
        bx, by = pts[(i + 1) % len(pts)]
        cx, cy = pts[(i + 2) % len(pts)]
        cross = (bx - ax) * (cy - by) - (by - ay) * (cx - bx)
        if abs(cross) < _EPS:
            continue
        s = 1 if cross > 0 else -1
        if sign == 0:
            sign = s
        elif s != sign:
            return False
    return True


def clip_by_convex(subject: Sequence[Point], clip: Sequence[Point]) -> Ring:
    """Sutherland-Hodgman: clip an arbitrary `subject` polygon by a CONVEX `clip`.

    Every clip polygon this module uses is convex by construction -- a mesh base
    outline is a convex hull, and so is the footprint's own hull -- which is
    what makes this exact and lets the geometry core stay dependency-free
    instead of pulling in a boolean-ops library for one operation.

    The subject may be concave; real OSM footprints usually are.
    """
    output = _counter_clockwise(subject)
    clip_ring = _counter_clockwise(clip)
    if len(output) < 3 or len(clip_ring) < 3:
        return []

    for i in range(len(clip_ring)):
        ax, ay = clip_ring[i]
        bx, by = clip_ring[(i + 1) % len(clip_ring)]
        ex, ey = bx - ax, by - ay

        def inside(p: Point) -> float:
            # Left of the directed edge, for a counter-clockwise clip ring.
            return ex * (p[1] - ay) - ey * (p[0] - ax)

        source, output = output, []
        if not source:
            return []

        prev = source[-1]
        prev_in = inside(prev)
        for cur in source:
            cur_in = inside(cur)
            if cur_in >= 0:
                if prev_in < 0:
                    output.append(_edge_intersection(prev, cur, prev_in, cur_in))
                output.append(cur)
            elif prev_in >= 0:
                output.append(_edge_intersection(prev, cur, prev_in, cur_in))
            prev, prev_in = cur, cur_in

    return output


def _edge_intersection(p: Point, q: Point, dp: float, dq: float) -> Point:
    denom = dp - dq
    t = 0.0 if abs(denom) < _EPS else dp / denom
    return (p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t)


def intersection_area(subject: Sequence[Point], convex_clip: Sequence[Point]) -> float:
    """Exact overlap area. `convex_clip` must be convex -- see `clip_by_convex`."""
    if len(open_ring(subject)) < 3 or len(open_ring(convex_clip)) < 3:
        return 0.0
    return area(clip_by_convex(subject, convex_clip))


def iou(subject: Sequence[Point], convex_clip: Sequence[Point]) -> float:
    """Intersection over union. 1 = identical, 0 = disjoint.

    Union is derived arithmetically (a + b - intersection), which is exact for
    simple polygons and avoids a second clipping pass.
    """
    a, b = area(subject), area(convex_clip)
    if a <= 0 or b <= 0:
        return 0.0
    inter = intersection_area(subject, convex_clip)
    union = a + b - inter
    return inter / union if union > 0 else 0.0


def bbox_overlap_area(a: Sequence[Point], b: Sequence[Point]) -> float:
    """Axis-aligned bounding-box overlap. The cheap gate before the exact test."""
    ba, bb = bounds(a), bounds(b)
    w = min(ba["maxX"], bb["maxX"]) - max(ba["minX"], bb["minX"])
    d = min(ba["maxY"], bb["maxY"]) - max(ba["minY"], bb["minY"])
    return w * d if w > 0 and d > 0 else 0.0
