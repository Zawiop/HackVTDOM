"""Unit tests for the degrees-to-meters and footprint geometry helpers."""

import math

from app.services import geo_math

LAT = 37.23  # Blacksburg, VA — the demo latitude.


def _rect(center_lng, center_lat, along_m, across_m, bearing_deg):
    """Build a rectangle of known real-world dimensions, rotated by `bearing_deg`."""
    per_lng, per_lat = geo_math.meters_per_degree(center_lat)
    theta = math.radians(bearing_deg)
    along = (math.sin(theta), math.cos(theta))
    across = (math.cos(theta), -math.sin(theta))

    corners = []
    for sa, sc in ((0.5, 0.5), (0.5, -0.5), (-0.5, -0.5), (-0.5, 0.5)):
        east = sa * along_m * along[0] + sc * across_m * across[0]
        north = sa * along_m * along[1] + sc * across_m * across[1]
        corners.append((center_lng + east / per_lng, center_lat + north / per_lat))
    corners.append(corners[0])  # closed ring, as OSM ways are
    return corners


def test_meters_per_degree_varies_with_latitude():
    eq_lng, eq_lat = geo_math.meters_per_degree(0.0)
    hi_lng, hi_lat = geo_math.meters_per_degree(60.0)

    assert 111_000 < eq_lng < 111_500
    assert 110_500 < eq_lat < 110_700
    # A degree of longitude halves by 60 degrees north — the whole reason the
    # spec says not to hardcode a constant.
    assert hi_lng < eq_lng * 0.55
    assert hi_lat > eq_lat  # a degree of latitude grows slightly toward the poles


def test_oriented_extents_recover_known_dimensions():
    for bearing in (0.0, 30.0, 45.0, 90.0, 137.0):
        ring = _rect(-80.42, LAT, along_m=80.0, across_m=40.0, bearing_deg=bearing)
        measured_bearing = geo_math.longest_edge_bearing_degrees(ring)
        assert abs(measured_bearing - bearing % 180.0) < 0.5, bearing

        width, depth = geo_math.oriented_extents_meters(ring, measured_bearing)
        assert abs(width - 80.0) < 0.5, (bearing, width)
        assert abs(depth - 40.0) < 0.5, (bearing, depth)


def test_axis_aligned_box_would_overstate_a_rotated_building():
    """Justifies using oriented extents instead of a raw lat/lng bounding box."""
    ring = _rect(-80.42, LAT, along_m=80.0, across_m=40.0, bearing_deg=45.0)
    box = geo_math.bounding_box(ring)
    per_lng, per_lat = geo_math.meters_per_degree(LAT)
    aa_width = (box["maxLng"] - box["minLng"]) * per_lng
    aa_depth = (box["maxLat"] - box["minLat"]) * per_lat

    width, depth = geo_math.oriented_extents_meters(ring, 45.0)
    assert abs(width - 80.0) < 0.5
    assert abs(depth - 40.0) < 0.5

    # The naive box reports a near-square for a building that is really 2:1,
    # overstating the short axis by more than double.
    assert abs(aa_width / aa_depth - 1.0) < 0.05
    assert aa_depth > 40.0 * 2.0


def test_point_in_polygon_and_distance():
    ring = _rect(-80.42, LAT, along_m=80.0, across_m=40.0, bearing_deg=0.0)

    assert geo_math.point_in_polygon((-80.42, LAT), ring)
    assert geo_math.distance_point_to_polygon_meters((-80.42, LAT), ring) == 0.0

    per_lng, _ = geo_math.meters_per_degree(LAT)
    outside = (-80.42 + (20.0 + 30.0) / per_lng, LAT)  # 30 m clear of the 40 m-wide face
    assert not geo_math.point_in_polygon(outside, ring)
    assert abs(geo_math.distance_point_to_polygon_meters(outside, ring) - 30.0) < 0.5


def test_centroid_of_known_rectangle():
    ring = _rect(-80.42, LAT, along_m=80.0, across_m=40.0, bearing_deg=25.0)
    cx, cy = geo_math.polygon_centroid(ring)
    assert abs(cx - (-80.42)) < 1e-6
    assert abs(cy - LAT) < 1e-6


def test_degenerate_rings_do_not_crash():
    assert geo_math.longest_edge_bearing_degrees([(-80.42, LAT)]) == 0.0
    assert geo_math.oriented_extents_meters([], 0.0) == (0.0, 0.0)
    assert not geo_math.point_in_polygon((0, 0), [(0, 0), (1, 1)])
