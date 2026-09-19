"""Parsing and ambiguity rules for step 02, exercised without touching Overpass."""

from app.routers import footprint
from app.services import geo_math

LAT, LNG = 37.23, -80.42


def _nodes(points):
    return [{"lat": p[1], "lon": p[0]} for p in points]


def _square(center_lng, center_lat, side_m):
    per_lng, per_lat = geo_math.meters_per_degree(center_lat)
    dx, dy = side_m / 2 / per_lng, side_m / 2 / per_lat
    return [
        (center_lng - dx, center_lat - dy),
        (center_lng + dx, center_lat - dy),
        (center_lng + dx, center_lat + dy),
        (center_lng - dx, center_lat + dy),
        (center_lng - dx, center_lat - dy),
    ]


def _way(osm_id, ring, name="Test Building"):
    return {
        "type": "way",
        "id": osm_id,
        "geometry": _nodes(ring),
        "tags": {"building": "yes", "name": name},
    }


def test_way_element_parses_to_candidate():
    ring = _square(LNG, LAT, 40.0)
    candidate = footprint._to_candidate(_way(1, ring), (LNG, LAT))

    assert candidate is not None
    assert candidate.osmId == 1
    assert candidate.distanceMeters == 0.0  # query point is inside
    assert abs(candidate.footprintWidthMeters - 40.0) < 0.5
    assert abs(candidate.footprintDepthMeters - 40.0) < 0.5
    assert candidate.tags["name"] == "Test Building"


def test_relation_outer_members_stitch_into_one_ring():
    """A multipolygon arrives as separate member ways, not a closed ring."""
    ring = _square(LNG, LAT, 40.0)[:-1]
    first_half, second_half = ring[:3], ring[2:] + [ring[0]]

    relation = {
        "type": "relation",
        "id": 99,
        "tags": {"building": "university", "type": "multipolygon"},
        "members": [
            {"type": "way", "ref": 1, "role": "outer", "geometry": _nodes(first_half)},
            {"type": "way", "ref": 2, "role": "outer", "geometry": _nodes(second_half)},
        ],
    }

    candidate = footprint._to_candidate(relation, (LNG, LAT))
    assert candidate is not None
    assert candidate.osmType == "relation"
    assert abs(candidate.footprintWidthMeters - 40.0) < 0.5
    assert candidate.distanceMeters == 0.0


def test_relation_stitches_a_reversed_member():
    ring = _square(LNG, LAT, 40.0)[:-1]
    first_half = ring[:3]
    second_half = list(reversed(ring[2:] + [ring[0]]))

    relation = {
        "type": "relation",
        "id": 100,
        "tags": {"building": "yes"},
        "members": [
            {"type": "way", "ref": 1, "role": "outer", "geometry": _nodes(first_half)},
            {"type": "way", "ref": 2, "role": "outer", "geometry": _nodes(second_half)},
        ],
    }

    candidate = footprint._to_candidate(relation, (LNG, LAT))
    assert candidate is not None
    assert abs(candidate.footprintWidthMeters - 40.0) < 0.5


def test_relation_inner_ring_is_ignored():
    outer = _square(LNG, LAT, 60.0)
    inner = _square(LNG, LAT, 10.0)
    relation = {
        "type": "relation",
        "id": 101,
        "tags": {"building": "yes"},
        "members": [
            {"type": "way", "ref": 1, "role": "outer", "geometry": _nodes(outer)},
            {"type": "way", "ref": 2, "role": "inner", "geometry": _nodes(inner)},
        ],
    }

    candidate = footprint._to_candidate(relation, (LNG, LAT))
    assert candidate is not None
    assert abs(candidate.footprintWidthMeters - 60.0) < 0.5


def test_single_containing_footprint_is_high_confidence():
    candidate = footprint._to_candidate(_way(1, _square(LNG, LAT, 40.0)), (LNG, LAT))
    selected, confidence, _ = footprint._resolve([candidate], (LNG, LAT))

    assert confidence == "auto-high"
    assert selected is candidate


def test_no_candidates_is_low_confidence():
    selected, confidence, reason = footprint._resolve([], (LNG, LAT))

    assert confidence == "auto-low"
    assert selected is None
    assert "No building" in reason


def test_equally_close_candidates_are_never_auto_picked():
    """The spec's core rule: ambiguity goes to the user, not to a coin flip."""
    per_lng, _ = geo_math.meters_per_degree(LAT)
    left = _way(1, _square(LNG - 25.0 / per_lng, LAT, 20.0), "Left")
    right = _way(2, _square(LNG + 25.0 / per_lng, LAT, 20.0), "Right")

    candidates = [
        footprint._to_candidate(left, (LNG, LAT)),
        footprint._to_candidate(right, (LNG, LAT)),
    ]
    candidates.sort(key=lambda c: c.distanceMeters)
    selected, confidence, reason = footprint._resolve(candidates, (LNG, LAT))

    assert confidence == "auto-low"
    assert selected is None
    assert "pick the right one" in reason


def test_clearly_nearest_candidate_is_selected():
    per_lng, _ = geo_math.meters_per_degree(LAT)
    near = _way(1, _square(LNG + 12.0 / per_lng, LAT, 20.0), "Near")
    far = _way(2, _square(LNG + 120.0 / per_lng, LAT, 20.0), "Far")

    candidates = [
        footprint._to_candidate(near, (LNG, LAT)),
        footprint._to_candidate(far, (LNG, LAT)),
    ]
    candidates.sort(key=lambda c: c.distanceMeters)
    selected, confidence, _ = footprint._resolve(candidates, (LNG, LAT))

    assert confidence == "auto-high"
    assert selected.tags["name"] == "Near"


def test_overlapping_footprints_are_ambiguous():
    a = _way(1, _square(LNG, LAT, 40.0), "A")
    b = _way(2, _square(LNG, LAT, 50.0), "B")
    candidates = [
        footprint._to_candidate(a, (LNG, LAT)),
        footprint._to_candidate(b, (LNG, LAT)),
    ]
    selected, confidence, reason = footprint._resolve(candidates, (LNG, LAT))

    assert confidence == "auto-low"
    assert selected is None
    assert "overlapping" in reason


def test_malformed_elements_are_dropped_not_fatal():
    assert footprint._to_candidate({"type": "way", "id": 1}, (LNG, LAT)) is None
    assert footprint._to_candidate(
        {"type": "way", "id": 1, "geometry": [{"lat": 1.0}]}, (LNG, LAT)
    ) is None
    assert footprint._to_candidate(
        {"type": "relation", "id": 1, "members": []}, (LNG, LAT)
    ) is None
