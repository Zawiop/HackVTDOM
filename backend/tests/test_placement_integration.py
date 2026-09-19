"""Step 08 against real upstream output: a real step 02 footprint result and a
real step 06/07 mesh, both checked in at `backend/assets/samples/`.

The ground-truth suite in test_placement.py proves the math. This proves the
module actually consumes what steps 02 and 07 really produce -- field names,
coordinate order, units and all.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.placement import compute_placement_transform

SAMPLES = Path(__file__).resolve().parent.parent / "assets" / "samples"
FOOTPRINT = SAMPLES / "burruss_footprint.json"
MESHES = [SAMPLES / "burruss_scorched.glb", SAMPLES / "burruss_flooded.glb"]

pytestmark = pytest.mark.skipif(
    not FOOTPRINT.exists() or not all(m.exists() for m in MESHES),
    reason="sample step 02/07 output not present",
)


@pytest.fixture(scope="module")
def footprint_result():
    return json.loads(FOOTPRINT.read_text())


@pytest.fixture(scope="module", params=[m.name for m in MESHES])
def transform(request, footprint_result):
    return compute_placement_transform(
        {
            "polygon": footprint_result["selected"],
            "neighbors": footprint_result["neighbors"],
            "confidence": footprint_result["confidence"],
        },
        {"path": str(SAMPLES / request.param), "upAxis": "y"},
    )


def test_accepts_a_step_02_result_verbatim(footprint_result):
    """No reshaping: `selected` + `neighbors` straight out of POST /api/footprint."""
    t = compute_placement_transform(
        {
            "selected": footprint_result["selected"],
            "neighbors": footprint_result["neighbors"],
            "confidence": footprint_result["confidence"],
        },
        {"path": str(MESHES[0]), "upAxis": "y"},
    )
    assert t["collision"]["neighborsChecked"] == len(footprint_result["neighbors"])


def test_output_has_the_five_fields_spec_08_names(transform):
    assert isinstance(transform["rotationDegrees"], float)
    assert isinstance(transform["scale"], float)
    assert len(transform["position"]) == 3
    assert transform["confidence"] in ("auto-high", "auto-low")
    assert len(transform["scoredRotationCandidates"]) == 4


def test_it_validates_against_the_persistence_contract(transform):
    """Step 11 stores this verbatim; Placement must accept it without loss."""
    from app.models.contracts import Placement

    stored = Placement(**transform)
    assert stored.rotationDegrees == transform["rotationDegrees"]
    assert stored.position == transform["position"]
    # extra="allow" keeps the diagnostics step 09 reads.
    assert stored.model_dump()["diagnostics"]["fitQuality"] == transform["diagnostics"]["fitQuality"]


def test_every_number_survives_a_json_round_trip(transform):
    """NaN or Infinity anywhere would break the Supabase write and the renderer."""
    round_tripped = json.loads(json.dumps(transform, allow_nan=False))
    assert round_tripped["scale"] == transform["scale"]


def test_the_mesh_lands_on_burruss_hall(transform, footprint_result):
    lat, lng, _ = transform["position"]
    box = footprint_result["selected"]["boundingBox"]

    # Inside the building's own bounding box, not merely in Virginia.
    assert box["minLat"] <= lat <= box["maxLat"]
    assert box["minLng"] <= lng <= box["maxLng"]


def test_rotation_is_a_usable_deck_gl_yaw(transform):
    yaw = transform["rotationDegrees"]
    assert 0 <= yaw < 360
    # layers.js feeds this straight into getOrientation as [0, yaw, 90].
    assert transform["scoredRotationCandidates"][0]["rotationDegrees"] == yaw


def test_scale_is_sane_for_a_step_07_mesh(transform):
    """Step 07 already sized the longest horizontal side to the footprint, so a
    correct fit should be close to 1 -- and nowhere near the `scale: 1` default
    that made every seeded building render one pixel wide."""
    assert 0.5 < transform["scale"] < 2.0
    assert transform["diagnostics"]["scaledHeightMeters"] > 5


def test_the_mesh_actually_covers_the_footprint(transform):
    d = transform["diagnostics"]
    # A single-view mesh will not match perfectly; it must still be recognisably
    # the same building rather than a blob parked nearby.
    assert d["fitQuality"] > 0.6
    assert d["iou"] <= d["maxAchievableIou"] + 1e-6
    assert d["placedMeshAreaSqM"] > 0.4 * d["footprintAreaSqM"]


def test_ground_alignment_uses_step_07s_base_centred_pivot(transform):
    # Step 07 puts the base at y=0, so nothing should need lifting.
    assert transform["ground"]["meshBaseOffsetUnits"] == pytest.approx(0, abs=0.01)
    assert transform["position"][2] == pytest.approx(0, abs=0.01)


def test_single_view_depth_shortfall_is_reported_not_hidden(transform):
    """Burruss is 70.8 m deep; a mesh reconstructed from one photograph guesses
    roughly half that. Step 08 stretches to fit and says so rather than leaving a
    building that is visibly too shallow on the map."""
    assert transform["scaleMode"] == "non-uniform"

    flag = next(f for f in transform["flags"] if f["code"] == "non-uniform-fallback")
    assert transform["scaleXYZ"][0] != pytest.approx(transform["scaleXYZ"][2], rel=0.01)
    assert 1.0 < transform["scaleStretchRatio"] < 2.5

    # Recorded, but not a reason to distrust the placement: this fires on every
    # single-view mesh, so treating it as a confidence signal would flag the
    # whole map and tell step 09 nothing.
    assert flag["severity"] == "info"


def test_a_good_single_view_mesh_is_not_routed_to_manual_correction(transform):
    """The point of the severity split: real pipeline output should come back
    auto-high when the geometry is actually fine."""
    low = [f for f in transform["flags"] if f["severity"] == "low"]
    assert low == [], low
    assert transform["confidence"] == "auto-high"


def test_neighbours_come_from_step_02_not_a_new_overpass_call(transform, footprint_result):
    assert transform["collision"]["neighborsChecked"] == len(footprint_result["neighbors"])
    assert transform["collision"]["neighborsChecked"] > 15


def test_http_route_end_to_end(client, footprint_result):
    res = client.post(
        "/api/placement",
        json={
            "footprint": {
                "polygon": footprint_result["selected"],
                "neighbors": footprint_result["neighbors"],
                "confidence": footprint_result["confidence"],
            },
            "mesh": {"path": str(MESHES[0]), "upAxis": "y"},
        },
    )

    assert res.status_code == 200
    body = res.json()
    assert len(body["scoredRotationCandidates"]) == 4
    assert body["collision"]["neighborsChecked"] > 15


def test_http_route_reports_an_unusable_mesh_as_422(client, footprint_result):
    res = client.post(
        "/api/placement",
        json={
            "footprint": {"polygon": footprint_result["selected"]},
            "mesh": {"path": "/no/such/mesh.glb"},
        },
    )
    assert res.status_code == 422


def test_http_route_rejects_a_missing_footprint(client):
    res = client.post("/api/placement", json={"footprint": {}, "mesh": {"path": "x.glb"}})
    assert res.status_code == 400
