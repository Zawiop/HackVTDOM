"""Step 08 — rotation search, scale fit, collision and confidence rules."""

import math

from app.services import geo_math, placement

LAT, LNG = 37.23, -80.42


def _rect_lnglat(center_lng, center_lat, along_m, across_m, bearing_deg):
    """A building footprint of known real-world size and orientation."""
    per_lng, per_lat = geo_math.meters_per_degree(center_lat)
    theta = math.radians(bearing_deg)
    along = (math.sin(theta), math.cos(theta))
    across = (math.cos(theta), -math.sin(theta))
    corners = []
    for sa, sc in ((0.5, 0.5), (0.5, -0.5), (-0.5, -0.5), (-0.5, 0.5)):
        east = sa * along_m * along[0] + sc * across_m * across[0]
        north = sa * along_m * along[1] + sc * across_m * across[1]
        corners.append((center_lng + east / per_lng, center_lat + north / per_lat))
    return corners


def _place(polygon, mesh_w, mesh_d, **kw):
    bearing = geo_math.longest_edge_bearing_degrees(polygon)
    return placement.compute_placement(polygon, bearing, mesh_w, mesh_d, **kw)


# --- rotation ---


def test_exact_match_scores_near_perfect_iou():
    polygon = _rect_lnglat(LNG, LAT, 80.0, 40.0, 30.0)
    result = _place(polygon, mesh_w=80.0, mesh_d=40.0)

    assert result["confidence"] == "auto-high"
    assert result["scoredRotationCandidates"][0]["iou"] > 0.98
    assert abs(result["scale"] - 1.0) < 0.02
    assert result["checks"]["rotation"]["ok"]


def test_rotation_search_recovers_the_building_bearing():
    for bearing in (0.0, 25.0, 65.0, 140.0):
        polygon = _rect_lnglat(LNG, LAT, 90.0, 30.0, bearing)
        result = _place(polygon, mesh_w=45.0, mesh_d=15.0)  # right shape, half size
        best = max(result["scoredRotationCandidates"], key=lambda c: c["iou"])
        # 0 and 180 are the same rectangle, so compare modulo 180.
        assert abs(best["rotationDegrees"] % 180.0 - bearing % 180.0) < 1.0, bearing
        assert best["iou"] > 0.95, bearing


def test_all_four_offsets_are_kept_for_step_09():
    polygon = _rect_lnglat(LNG, LAT, 80.0, 40.0, 10.0)
    result = _place(polygon, mesh_w=80.0, mesh_d=40.0)

    offsets = sorted(c["offsetDegrees"] for c in result["scoredRotationCandidates"])
    assert offsets == [0.0, 90.0, 180.0, 270.0]
    # Step 09 replays these as buttons, so each needs its own scale too.
    assert all("scale" in c and "iou" in c for c in result["scoredRotationCandidates"])


def test_opposite_rotations_tie_because_the_mesh_is_a_rectangle():
    """Documents the known limit: IoU cannot tell a facade from its back."""
    polygon = _rect_lnglat(LNG, LAT, 80.0, 40.0, 30.0)
    result = _place(polygon, mesh_w=80.0, mesh_d=40.0)
    by_offset = {c["offsetDegrees"]: c["iou"] for c in result["scoredRotationCandidates"]}

    assert abs(by_offset[0.0] - by_offset[180.0]) < 1e-6
    assert abs(by_offset[90.0] - by_offset[270.0]) < 1e-6
    assert "step 09" in result["rotation_note"]


def test_near_square_footprint_is_flagged_not_guessed():
    polygon = _rect_lnglat(LNG, LAT, 50.0, 49.0, 20.0)
    result = _place(polygon, mesh_w=50.0, mesh_d=49.0)

    assert result["checks"]["rotation"]["ok"] is False
    assert result["confidence"] == "auto-low"
    assert "human" in result["checks"]["rotation"]["detail"]


# --- scale ---


def test_uniform_scale_fits_a_half_size_mesh():
    polygon = _rect_lnglat(LNG, LAT, 80.0, 40.0, 0.0)
    result = _place(polygon, mesh_w=40.0, mesh_d=20.0)

    assert abs(result["scale"] - 2.0) < 0.02
    assert result["scaleXYZ"] is None
    assert result["checks"]["scale"]["ok"]


def test_a_shallow_mesh_gets_a_stretch_hint_but_is_not_flagged():
    """Single-photo meshes systematically under-read depth; that is not a failure.

    Mirrors the real captured output: SF3D returned 101.88 x 37.57 m for a
    footprint measuring 101.88 x 70.79, a 47% shortfall on the free axis.
    """
    polygon = _rect_lnglat(LNG, LAT, 101.88, 70.79, 0.0)
    result = _place(polygon, mesh_w=101.88, mesh_d=37.57)

    assert result["checks"]["scale"]["ok"] is True
    assert abs(result["scale"] - 1.0) < 0.01
    # The non-uniform option is still offered, it just is not a flag.
    assert result["scaleXYZ"] is not None
    assert any("shallower" in w for w in result["warnings"])


def test_wildly_mismatched_proportions_are_flagged_as_a_units_problem():
    # Mesh is 1:1, footprint is 4:1 — a 75% shortfall, past what depth inference explains.
    polygon = _rect_lnglat(LNG, LAT, 80.0, 20.0, 0.0)
    result = _place(polygon, mesh_w=40.0, mesh_d=40.0)

    assert result["checks"]["scale"]["ok"] is False
    assert result["confidence"] == "auto-low"
    assert result["scaleXYZ"] is not None
    # `scale` stays proportion-preserving, which is the stated preference.
    assert abs(result["scale"] - 0.5) < 0.02
    assert "units" in result["checks"]["scale"]["detail"]


def test_rotation_ceiling_accounts_for_a_mesh_smaller_than_the_footprint():
    """A shallow mesh caps IoU by area, not by being wrongly oriented."""
    polygon = _rect_lnglat(LNG, LAT, 101.88, 70.79, 0.0)
    result = _place(polygon, mesh_w=101.88, mesh_d=37.57)

    # The mesh covers ~53% of the footprint, so no rotation can beat that.
    assert result["achievableIou"] < 0.6
    assert result["rectangularity"] > 0.95  # the footprint itself is a clean rectangle
    # Correctly oriented despite the low absolute IoU.
    assert result["checks"]["rotation"]["ok"] is True


# --- collision ---


def test_overlapping_neighbour_is_flagged():
    polygon = _rect_lnglat(LNG, LAT, 60.0, 60.0, 0.0)
    per_lng, _ = geo_math.meters_per_degree(LAT)
    neighbour = _rect_lnglat(LNG + 20.0 / per_lng, LAT, 60.0, 60.0, 0.0)

    result = _place(polygon, 60.0, 60.0, neighbors_lnglat=[neighbour])
    assert result["checks"]["collision"]["ok"] is False
    assert result["confidence"] == "auto-low"


def test_diagonal_neighbour_whose_bounding_box_overlaps_is_not_flagged():
    """The reason collision uses real polygon overlap, not axis-aligned boxes.

    Two thin buildings at 45 degrees, offset along their own axis: their
    axis-aligned bounding boxes overlap heavily while the buildings never touch.
    """
    polygon = _rect_lnglat(LNG, LAT, 80.0, 40.0, 45.0)
    per_lng, per_lat = geo_math.meters_per_degree(LAT)
    # 100 m apart along their shared 45-degree axis: a clear 20 m gap between two
    # 80 m buildings, while their axis-aligned boxes still overlap by ~14 m.
    offset = 100.0 / math.sqrt(2)
    neighbour = _rect_lnglat(
        LNG + offset / per_lng, LAT + offset / per_lat, 80.0, 40.0, 45.0
    )

    mesh_box = geo_math.bounding_box(polygon)
    nb_box = geo_math.bounding_box(neighbour)
    assert nb_box["minLng"] < mesh_box["maxLng"], "test setup: bounding boxes must overlap"
    assert nb_box["minLat"] < mesh_box["maxLat"], "test setup: bounding boxes must overlap"

    result = _place(polygon, 80.0, 40.0, neighbors_lnglat=[neighbour])
    assert result["checks"]["collision"]["ok"], result["checks"]["collision"]["detail"]


def test_l_shaped_building_is_judged_against_its_own_ceiling():
    """An L-shape can never reach IoU 1.0, so it must not be flagged for that alone."""
    per_lng, per_lat = geo_math.meters_per_degree(LAT)
    m = lambda e, n: (LNG + e / per_lng, LAT + n / per_lat)  # noqa: E731
    l_shape = [m(-30, -20), m(30, -20), m(30, 0), m(0, 0), m(0, 20), m(-30, 20)]

    result = _place(l_shape, mesh_w=60.0, mesh_d=40.0)
    assert 0.35 < result["rectangularity"] < 0.9
    # Judged relative to the ceiling, not against a flat 1.0.
    assert result["checks"]["rotation"]["ok"], result["checks"]["rotation"]["detail"]


def test_very_irregular_footprint_is_sent_to_a_human():
    per_lng, per_lat = geo_math.meters_per_degree(LAT)
    m = lambda e, n: (LNG + e / per_lng, LAT + n / per_lat)  # noqa: E731
    # A thin cross: fills very little of its bounding box.
    cross = [
        m(-5, -40), m(5, -40), m(5, -5), m(40, -5), m(40, 5), m(5, 5),
        m(5, 40), m(-5, 40), m(-5, 5), m(-40, 5), m(-40, -5), m(-5, -5),
    ]
    result = _place(cross, mesh_w=80.0, mesh_d=80.0)

    assert result["rectangularity"] < 0.35
    assert result["checks"]["rotation"]["ok"] is False
    assert result["confidence"] == "auto-low"
    assert "human" in result["checks"]["rotation"]["detail"]


def test_distant_neighbour_does_not_collide():
    polygon = _rect_lnglat(LNG, LAT, 80.0, 40.0, 0.0)
    per_lng, _ = geo_math.meters_per_degree(LAT)
    neighbour = _rect_lnglat(LNG + 300.0 / per_lng, LAT, 60.0, 60.0, 0.0)

    result = _place(polygon, 80.0, 40.0, neighbors_lnglat=[neighbour])
    assert result["checks"]["collision"]["ok"]
    assert result["confidence"] == "auto-high"


# --- confidence propagation ---


def test_ambiguous_footprint_from_step_02_is_not_laundered():
    polygon = _rect_lnglat(LNG, LAT, 80.0, 40.0, 30.0)
    result = _place(polygon, 80.0, 40.0, footprint_confidence="auto-low")

    assert result["confidence"] == "auto-low"
    assert result["checks"]["footprintMatch"]["ok"] is False
    # A clean later check must not overwrite the earlier flag.
    assert result["checks"]["rotation"]["ok"] is True


def test_position_is_lat_lng_z_at_ground_level():
    polygon = _rect_lnglat(LNG, LAT, 80.0, 40.0, 0.0)
    result = _place(polygon, 80.0, 40.0)

    lat, lng, z = result["position"]
    assert abs(lat - LAT) < 1e-5
    assert abs(lng - LNG) < 1e-5
    assert z == 0.0


def test_zero_mesh_extents_are_rejected():
    polygon = _rect_lnglat(LNG, LAT, 80.0, 40.0, 0.0)
    try:
        _place(polygon, 0.0, 40.0)
    except ValueError as exc:
        assert "positive metres" in str(exc)
    else:
        raise AssertionError("expected ValueError")


# --- geometry primitives ---


def test_iou_of_identical_squares_is_one():
    square = geo_math.oriented_rectangle((0.0, 0.0), 10.0, 10.0, 0.0)
    assert abs(geo_math.intersection_over_union(square, square) - 1.0) < 1e-6


def test_iou_of_disjoint_squares_is_zero():
    a = geo_math.oriented_rectangle((0.0, 0.0), 10.0, 10.0, 0.0)
    b = geo_math.oriented_rectangle((100.0, 0.0), 10.0, 10.0, 0.0)
    assert geo_math.intersection_over_union(a, b) == 0.0


def test_iou_of_half_overlapping_squares():
    a = geo_math.oriented_rectangle((0.0, 0.0), 10.0, 10.0, 0.0)
    b = geo_math.oriented_rectangle((5.0, 0.0), 10.0, 10.0, 0.0)
    # Intersection 50, union 150.
    assert abs(geo_math.intersection_over_union(a, b) - 1.0 / 3.0) < 1e-6


def test_clipping_handles_a_concave_subject():
    """An L-shaped building clipped by a rectangle keeps only the covered arm."""
    l_shape = [(0, 0), (20, 0), (20, 10), (10, 10), (10, 20), (0, 20)]
    clip = geo_math.oriented_rectangle((5.0, 5.0), 10.0, 10.0, 0.0)
    area = geo_math.polygon_area_2d(geo_math.clip_polygon_convex(l_shape, clip))
    assert abs(area - 100.0) < 1e-6
