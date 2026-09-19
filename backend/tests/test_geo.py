from __future__ import annotations

import pytest

from app.services.geo import haversine_meters, meters_per_degree, offset_meters, within_radius


def test_zero_distance():
    assert haversine_meters(37.2295, -80.4234, 37.2295, -80.4234) == pytest.approx(0.0)


def test_known_separation_burruss_to_torgersen():
    """~850m across the VT drillfield — sanity anchor, not a precision claim."""
    d = haversine_meters(37.2284, -80.4234, 37.2296, -80.4139)
    assert 800 < d < 900


def test_offset_meters_roundtrips_within_tolerance():
    lat, lng = offset_meters(37.2295, -80.4234, 10.0, 0.0)
    assert haversine_meters(37.2295, -80.4234, lat, lng) == pytest.approx(10.0, abs=0.1)


def test_longitude_degree_shrinks_with_latitude():
    _, eq = meters_per_degree(0.0)
    _, vt = meters_per_degree(37.2295)
    assert eq > vt, "a degree of longitude is shorter away from the equator"


def test_within_radius_filters_and_sorts():
    origin = (37.2295, -80.4234)
    near, _ = offset_meters(*origin, 30.0, 0.0), None
    far_lat, far_lng = offset_meters(*origin, 400.0, 0.0)
    near_lat, near_lng = offset_meters(*origin, 30.0, 0.0)
    mid_lat, mid_lng = offset_meters(*origin, 120.0, 0.0)

    pts = [
        {"name": "far", "lat": far_lat, "lng": far_lng},
        {"name": "mid", "lat": mid_lat, "lng": mid_lng},
        {"name": "near", "lat": near_lat, "lng": near_lng},
    ]
    got = within_radius(origin, pts, 250)
    assert [p["name"] for p in got] == ["near", "mid"], "far is outside, results nearest-first"
    assert got[0]["distance_m"] == pytest.approx(30.0, abs=0.2)


def test_within_radius_skips_points_missing_coords():
    assert within_radius((37.0, -80.0), [{"lat": None, "lng": -80.0}], 100) == []
