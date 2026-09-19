"""Step 08 -- the placement transform (08-placement-transform.md).

Ground-truth tests: every mesh here is built from a *real* OSM building polygon
with a known rotation, scale and vertical offset baked in, so a pass means the
math recovered exactly what was applied rather than merely looking plausible.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from app.services import placement_geom as g
from app.services.placement import PlacementInputError, compute_placement_transform
from tests.helpers import (
    all_buildings,
    angle_error,
    block_glb,
    building_named,
    centred_ring,
    extrude_to_glb,
    local_ring,
    neighbors_of,
    prism_glb,
)

SAMPLES = Path(__file__).resolve().parent.parent / "assets" / "samples"


def place(building, mesh_path, neighbors=None, confidence=None, options=None):
    return compute_placement_transform(
        {
            "polygon": building,
            "neighbors": neighbors or [],
            **({"confidence": confidence} if confidence else {}),
        },
        {"path": str(mesh_path), "upAxis": "y"},
        options,
    )


def offset_from_centroid_m(transform, building) -> float:
    """How far the returned origin landed from the footprint's own centroid."""
    ring = local_ring(building)
    cx, cy = g.centroid(ring)
    # local_ring is anchored on the polygon centroid, so the target is ~(0, 0);
    # re-project the returned lat/lng into the same frame to compare.
    from app.services.geo_math import meters_per_degree, polygon_centroid

    pts = [(p[0], p[1]) for p in building["geometry"]]
    alng, alat = polygon_centroid(pts)
    per_lng, per_lat = meters_per_degree(alat)
    ex = (transform["position"][1] - alng) * per_lng
    ny = (transform["position"][0] - alat) * per_lat
    return math.hypot(ex - cx, ny - cy)


# --- ground truth ---------------------------------------------------------


def test_mesh_built_from_the_footprint_places_essentially_perfectly(tmp_path):
    building = building_named("Davidson Hall")
    mesh = extrude_to_glb(centred_ring(building), tmp_path / "m.glb", height_meters=18)

    t = place(building, mesh)
    d = t["diagnostics"]

    # The mesh IS the footprint, so placement should reach the ceiling a convex
    # base outline can achieve against this (concave) polygon.
    assert d["fitQuality"] > 0.99
    assert d["iou"] == pytest.approx(d["maxAchievableIou"], abs=0.01)
    assert t["scale"] == pytest.approx(1.0, abs=0.02)
    assert t["scaleMode"] == "uniform"
    assert t["confidence"] == "auto-high"
    assert t["flags"] == []


@pytest.mark.parametrize("pre_rotate", [0, 37, 90, 145, 213, 300])
def test_recovers_a_baked_rotation(tmp_path, pre_rotate):
    building = building_named("Derring Hall")
    mesh = extrude_to_glb(
        centred_ring(building), tmp_path / f"m{pre_rotate}.glb", pre_rotate_degrees=pre_rotate
    )

    t = place(building, mesh)

    # A mesh rotated by +pre_rotate in compass terms needs heading -pre_rotate to
    # undo it, and the renderer's yaw runs opposite to the compass, so the
    # returned yaw is +pre_rotate.
    assert angle_error(t["rotationDegrees"], pre_rotate) < 2
    assert t["diagnostics"]["fitQuality"] > 0.95
    assert t["scale"] == pytest.approx(1.0, abs=0.02)


def test_keeps_four_candidates_ninety_degrees_apart_for_step_09(tmp_path):
    building = building_named("Norris Hall")
    mesh = extrude_to_glb(centred_ring(building), tmp_path / "m.glb")

    t = place(building, mesh)
    cands = t["scoredRotationCandidates"]

    assert len(cands) == 4
    assert sorted(c["offsetDegrees"] for c in cands) == [0, 90, 180, 270]

    # Sorted best-first, every one scored, none discarded.
    ious = [c["iou"] for c in cands]
    assert ious == sorted(ious, reverse=True)
    assert t["rotationDegrees"] == cands[0]["rotationDegrees"]
    for c in cands:
        assert 0.0 <= c["iou"] <= 1.0
        assert c["scale"] > 0

    headings = sorted(c["rotationDegrees"] % 360 for c in cands)
    for a, b in zip(headings, headings[1:]):
        assert b - a == pytest.approx(90, abs=0.01)


@pytest.mark.parametrize("name", ["Davidson Hall", "Patton Hall", "War Memorial Hall"])
def test_lands_on_the_footprint_not_elsewhere_on_the_planet(tmp_path, name):
    building = building_named(name)
    mesh = extrude_to_glb(centred_ring(building), tmp_path / "m.glb", pre_rotate_degrees=63)

    t = place(building, mesh)
    lat, lng, _ = t["position"]

    assert offset_from_centroid_m(t, building) < 2
    assert 37.2 < lat < 37.3
    assert -80.5 < lng < -80.4


# --- scale ----------------------------------------------------------------


def test_prefers_a_single_uniform_factor_when_proportions_match(tmp_path):
    building = building_named("Hancock Hall")
    mesh = extrude_to_glb(centred_ring(building), tmp_path / "m.glb", pre_scale=0.5)

    t = place(building, mesh)

    assert t["scaleMode"] == "uniform"
    assert t["scale"] == pytest.approx(2.0, rel=0.05)
    assert t["scaleXYZ"][0] == pytest.approx(t["scaleXYZ"][2])


def test_falls_back_to_non_uniform_past_the_undersize_threshold(tmp_path):
    building = building_named("Davidson Hall")
    rect = g.min_area_rectangle(local_ring(building))

    # Matches the building's long axis but only a third as deep: uniform scaling
    # would leave it at ~33% coverage, far past the ~30%-undersized threshold.
    mesh = block_glb(tmp_path / "m.glb", rect["length"], rect["width"] / 3, 15)

    t = place(building, mesh)

    assert t["scaleMode"] == "non-uniform"
    assert t["scaleXYZ"][0] != pytest.approx(t["scaleXYZ"][2], rel=0.01)
    assert t["confidence"] == "auto-low"
    assert "non-uniform-fallback" in [f["code"] for f in t["flags"]]


def test_does_not_stretch_a_mesh_only_slightly_off_proportion(tmp_path):
    building = building_named("Hahn Hall South")
    rect = g.min_area_rectangle(local_ring(building))

    mesh = block_glb(tmp_path / "m.glb", rect["length"], rect["width"] * 0.9, 15)
    t = place(building, mesh)

    assert t["scaleMode"] == "uniform"
    assert "non-uniform-fallback" not in [f["code"] for f in t["flags"]]


def test_flags_a_units_problem_instead_of_absorbing_it(tmp_path):
    building = building_named("Norris Hall")
    # Authored in centimetres rather than metres -- step 07's job to catch.
    mesh = extrude_to_glb(centred_ring(building), tmp_path / "m.glb", pre_scale=0.01)

    t = place(building, mesh)

    assert t["scale"] == pytest.approx(100, rel=0.05)
    assert t["confidence"] == "auto-low"
    flag = next(f for f in t["flags"] if f["code"] == "implausible-scale")
    assert flag["subStep"] == "mesh"
    assert "units problem" in flag["message"]


# --- ground alignment -----------------------------------------------------


def test_z_is_zero_when_step_07_base_centred_the_pivot(tmp_path):
    building = building_named("Patton Hall")
    mesh = extrude_to_glb(centred_ring(building), tmp_path / "m.glb", height_meters=20)

    t = place(building, mesh)

    assert t["position"][2] == pytest.approx(0, abs=1e-6)
    assert t["ground"]["meshBaseOffsetUnits"] == pytest.approx(0, abs=1e-6)


def test_sinks_a_floating_mesh_back_to_the_ground_and_says_so(tmp_path):
    building = building_named("Patton Hall")
    mesh = extrude_to_glb(centred_ring(building), tmp_path / "m.glb", height_meters=20, base_offset=7)

    t = place(building, mesh)

    assert t["ground"]["meshBaseOffsetUnits"] == pytest.approx(7, abs=0.01)
    assert t["position"][2] == pytest.approx(-7 * t["scaleXYZ"][1], abs=0.05)
    assert "pivot-not-base-centred" in [f["code"] for f in t["flags"]]


def test_lifts_a_sunken_mesh_up_to_the_ground(tmp_path):
    building = building_named("Patton Hall")
    mesh = extrude_to_glb(centred_ring(building), tmp_path / "m.glb", base_offset=-4)

    t = place(building, mesh)

    assert t["position"][2] > 0
    assert t["position"][2] == pytest.approx(4 * t["scaleXYZ"][1], abs=0.05)


def test_scaled_height_stays_physically_plausible(tmp_path):
    building = building_named("Derring Hall")
    mesh = extrude_to_glb(centred_ring(building), tmp_path / "m.glb", height_meters=24)

    t = place(building, mesh)
    assert 15 < t["diagnostics"]["scaledHeightMeters"] < 40


# --- collision ------------------------------------------------------------


def test_reuses_step_02_neighbours_and_reports_a_clean_placement(tmp_path):
    building = building_named("War Memorial Hall")
    nbrs = neighbors_of(building)
    mesh = extrude_to_glb(centred_ring(building), tmp_path / "m.glb")

    t = place(building, mesh, neighbors=nbrs)

    assert t["collision"]["neighborsChecked"] == len(nbrs)
    assert t["collision"]["neighborsChecked"] > 10
    assert t["collision"]["worstOverlapRatio"] < 0.15
    assert "neighbor-overlap" not in [f["code"] for f in t["flags"]]


def test_never_counts_the_target_as_its_own_neighbour(tmp_path):
    building = building_named("Davidson Hall")
    mesh = extrude_to_glb(centred_ring(building), tmp_path / "m.glb")

    # Pass the whole set, target included, the way a naive step 02 result would.
    t = place(building, mesh, neighbors=list(all_buildings()))

    assert t["collision"]["neighborsChecked"] == len(all_buildings()) - 1
    ids = [str(o["neighborId"]) for o in t["collision"]["overlaps"]]
    assert str(building["osmId"]) not in ids


def test_flags_a_real_overlap(tmp_path):
    building = building_named("Davidson Hall")

    # Inflating the *footprint* is what makes the placed mesh spill across the
    # buildings next door. Inflating the mesh alone would not: the scale fit
    # simply shrinks an oversized mesh back onto the footprint it was given.
    from app.services.geo_math import meters_per_degree, polygon_centroid

    pts = [(p[0], p[1]) for p in building["geometry"]]
    alng, alat = polygon_centroid(pts)
    per_lng, per_lat = meters_per_degree(alat)
    inflated = {
        **building,
        "geometry": [[alng + (p[0] - alng) * 4, alat + (p[1] - alat) * 4] for p in pts],
    }

    mesh = extrude_to_glb(centred_ring(inflated), tmp_path / "m.glb", height_meters=20)
    t = place(inflated, mesh, neighbors=neighbors_of(building))

    assert len(t["collision"]["overlaps"]) > 0
    assert t["collision"]["worstOverlapRatio"] > 0.15
    assert t["confidence"] == "auto-low"
    assert "neighbor-overlap" in [f["code"] for f in t["flags"]]


def test_diagonal_neighbours_whose_boxes_touch_are_not_false_positives(tmp_path):
    """Campus sits at ~45 degrees to the compass, so axis-aligned boxes overlap
    constantly while the buildings are metres apart. None of these are real."""
    flagged = 0
    for building in all_buildings():
        mesh = extrude_to_glb(centred_ring(building), tmp_path / "m.glb", height_meters=20)
        t = place(building, mesh, neighbors=neighbors_of(building))
        if "neighbor-overlap" in [f["code"] for f in t["flags"]]:
            flagged += 1
    assert flagged == 0


# --- confidence -----------------------------------------------------------


def test_propagates_step_02_low_confidence_as_a_distinct_flag(tmp_path):
    building = building_named("Norris Hall")
    mesh = extrude_to_glb(centred_ring(building), tmp_path / "m.glb")

    t = place(building, mesh, confidence="auto-low")

    assert t["confidence"] == "auto-low"
    flag = next(f for f in t["flags"] if f["subStep"] == "footprint")
    assert flag["code"] == "footprint-match-low"


def test_a_later_clean_check_never_clears_an_earlier_flag(tmp_path):
    building = building_named("Norris Hall")
    mesh = extrude_to_glb(centred_ring(building), tmp_path / "m.glb")

    t = place(building, mesh, neighbors=neighbors_of(building), confidence="auto-low")

    # Rotation, scale, collision and ground all pass...
    assert t["diagnostics"]["fitQuality"] > 0.95
    assert t["collision"]["worstOverlapRatio"] < 0.15
    assert t["position"][2] == pytest.approx(0, abs=1e-6)
    # ...and it is still auto-low, with the one original reason intact.
    assert t["confidence"] == "auto-low"
    assert len(t["flags"]) == 1


def test_flags_a_mesh_of_the_wrong_shape(tmp_path):
    building = building_named("Sandy Hall")  # near-rectangular in plan
    rect = g.min_area_rectangle(local_ring(building))

    # A triangle fills about half the rectangle it is inscribed in however it is
    # rotated or scaled, so fit quality cannot reach the threshold.
    mesh = prism_glb(tmp_path / "m.glb", rect["length"], rect["width"], 12)
    t = place(building, mesh)

    assert t["diagnostics"]["fitQuality"] < 0.6
    assert t["confidence"] == "auto-low"
    assert "low-iou" in [f["code"] for f in t["flags"]]


def test_reports_step_02_derived_values_disagreeing(tmp_path):
    building = building_named("Patton Hall")
    mesh = extrude_to_glb(centred_ring(building), tmp_path / "m.glb")

    t = compute_placement_transform(
        {"polygon": {**building, "footprintWidthMeters": 999, "rotationDegrees": 7}},
        {"path": mesh, "upAxis": "y"},
    )

    assert t["confidence"] == "auto-low"
    flag = next(f for f in t["flags"] if f["code"] == "derived-values-disagree")
    assert "footprintWidthMeters reported 999" in flag["message"]
    assert t["diagnostics"]["footprintDerivedMismatch"]


def test_the_180_flip_is_reported_not_flagged(tmp_path):
    building = building_named("Derring Hall")
    mesh = extrude_to_glb(centred_ring(building), tmp_path / "m.glb")

    t = place(building, mesh)

    # The flip scores almost as well -- a footprint cannot tell a facade from its
    # back -- and that is information for step 09, not a confidence problem.
    assert t["diagnostics"]["rotationFlipMargin"] is not None
    assert abs(t["diagnostics"]["rotationFlipMargin"]) < 0.1
    assert "rotation-ambiguous" not in [f["code"] for f in t["flags"]]
    assert t["confidence"] == "auto-high"


def test_a_genuine_across_vs_along_ambiguity_is_still_flagged(tmp_path):
    building = building_named("Sandy Hall")
    rect = g.min_area_rectangle(local_ring(building))

    # A square fits equally well at every quadrant: the real ambiguity, 90
    # degrees out rather than 180.
    mesh = block_glb(tmp_path / "m.glb", rect["length"], rect["length"], 12)
    t = place(building, mesh)

    assert "rotation-ambiguous" in [f["code"] for f in t["flags"]]
    assert t["confidence"] == "auto-low"


def test_every_real_building_places_at_auto_high_against_its_own_footprint(tmp_path):
    """The strongest end-to-end assertion available: a mesh that genuinely is the
    building must never be routed to manual correction."""
    for building in all_buildings():
        mesh = extrude_to_glb(centred_ring(building), tmp_path / "m.glb", height_meters=20)
        t = place(building, mesh, neighbors=neighbors_of(building))

        name = building["tags"].get("name", building["osmId"])
        assert t["confidence"] == "auto-high", f"{name}: {t['flags']}"
        assert t["diagnostics"]["fitQuality"] > 0.95, name
        assert t["scale"] == pytest.approx(1.0, abs=0.05), name
        assert t["position"][2] == pytest.approx(0, abs=1e-6), name


# --- handedness -----------------------------------------------------------


def test_mesh_frame_is_a_rotation_not_a_mirror(tmp_path):
    """glTF is right-handed, so with Y up the geographic mapping must be
    east = +X, **north = -Z**. Mapping north to +Z instead reflects the mesh.

    The tell is that a mirrored outline can score *above* the ceiling a convex
    outline is able to reach against the true polygon -- which is impossible, and
    is exactly what the wrong mapping produced on real Burruss Hall data.
    """
    building = building_named("Davidson Hall")
    mesh = extrude_to_glb(centred_ring(building), tmp_path / "m.glb")

    t = place(building, mesh)
    d = t["diagnostics"]

    assert d["iou"] <= d["maxAchievableIou"] + 1e-6
    assert d["fitQuality"] <= 1.0 + 1e-6


# --- input validation -----------------------------------------------------


def test_rejects_a_polygon_with_too_few_vertices(tmp_path):
    mesh = block_glb(tmp_path / "m.glb", 10, 10, 10)
    with pytest.raises(PlacementInputError):
        compute_placement_transform(
            {"polygon": {"geometry": [[-80.4, 37.2], [-80.3, 37.2]]}},
            {"path": mesh, "upAxis": "y"},
        )


def test_rejects_a_footprint_too_small_to_place_against(tmp_path):
    mesh = block_glb(tmp_path / "m.glb", 10, 10, 10)
    tiny = [[-80.4234, 37.2284], [-80.42339, 37.2284], [-80.42339, 37.22841]]
    with pytest.raises(PlacementInputError, match="too small"):
        compute_placement_transform({"polygon": {"geometry": tiny}}, {"path": mesh, "upAxis": "y"})


def test_rejects_a_mesh_input_with_nothing_to_load():
    with pytest.raises(PlacementInputError):
        compute_placement_transform({"polygon": building_named("Norris Hall")}, {})


def test_reports_a_missing_mesh_file_as_bad_input():
    with pytest.raises(PlacementInputError, match="not/here"):
        compute_placement_transform(
            {"polygon": building_named("Norris Hall")},
            {"path": "/definitely/not/here.glb", "upAxis": "y"},
        )
