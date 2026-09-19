"""Entrance projection + marker baking (no detector model needed). Offline and fast.

The door detector itself is exercised in test_entrances_heavy.py (pytest -m heavy).
"""
import io
import json
import struct

import numpy as np
import pytest
import trimesh

from app.generation import entrances


def glb_doc(glb: bytes) -> dict:
    n = struct.unpack("<I", glb[12:16])[0]
    return json.loads(glb[20 : 20 + n])


def facade_box() -> trimesh.Trimesh:
    """A 40 x 12 x 10 m block in the normalized frame: base at y=0, facade face at z=+5."""
    box = trimesh.creation.box(extents=[40, 12, 10])
    box.apply_translation([0, 6, 0])
    return box


# A camera 30 m in front of the facade at eye height, looking straight at it (-Z), 40 deg FOV.
CAMERA = {"position": (0, 6, 30), "forward": (0, 0, -1), "up": (0, 1, 0), "right": (1, 0, 0), "fovy": 40.0}
FRAME = (500.0, 500.0, 1000.0)  # crop square: pixel (x, y) -> u = x/1000, v = y/1000


def pixel_on_facade(x_m: float, y_m: float) -> tuple[float, float]:
    """Inverse of the ray model for a point on the z=+5 facade (25 m from the camera)."""
    t = np.tan(np.radians(20))
    u = (x_m / 25 / t + 1) / 2
    v = (1 - (y_m - 6) / 25 / t) / 2
    return u * 1000, v * 1000


def test_door_box_projects_onto_the_facade():
    # A 3 m wide x 4 m tall door, bottom-center at x = -8 m, standing on the ground.
    x0, y0 = pixel_on_facade(-9.5, 4.0)
    x1, y1 = pixel_on_facade(-6.5, 0.0)
    det = {"box": [x0, y0, x1, y1], "score": 0.5, "label": "a door"}
    ents, warnings = entrances.place_entrances(facade_box(), [det], CAMERA, np.eye(4), FRAME)
    assert warnings == [] and len(ents) == 1
    e = ents[0]
    assert e["position"][0] == pytest.approx(-8.0, abs=0.05)
    assert e["position"][1] == 0.0  # snapped to the ground
    assert e["position"][2] == pytest.approx(5 + entrances.MARKER_OFFSET_M, abs=0.05)  # just proud of the wall
    assert e["facing"] == pytest.approx([0, 0, 1], abs=1e-3)
    assert e["widthMeters"] == pytest.approx(3.0, rel=0.02)
    assert e["heightMeters"] == pytest.approx(4.0, rel=0.02)
    assert e["source"] == "detected" and e["confidence"] == "auto-high"


def test_camera_follows_the_normalization_transform():
    # The provider's raw frame is 10x smaller; normalization scales it up and shifts it +2 m in
    # X. The camera must ride the same transform, so camera, building and door all move +2 m.
    to_norm = trimesh.transformations.translation_matrix([2, 0, 0]) @ np.diag([10, 10, 10, 1.0])
    raw_cam = dict(CAMERA, position=tuple(np.array(CAMERA["position"]) / 10))
    box = facade_box()
    box.apply_translation([2, 0, 0])
    x0, y0 = pixel_on_facade(-9.5, 4.0)
    x1, y1 = pixel_on_facade(-6.5, 0.0)
    ents, _ = entrances.place_entrances(box, [{"box": [x0, y0, x1, y1], "score": 0.5}], raw_cam, to_norm, FRAME)
    assert ents[0]["position"][0] == pytest.approx(-6.0, abs=0.05)  # -8 m, shifted by the +2 m
    assert ents[0]["widthMeters"] == pytest.approx(3.0, rel=0.02)


def test_door_that_misses_the_mesh_is_skipped():
    x0, y0 = pixel_on_facade(30, 4.0)  # off the end of the 40 m block
    x1, y1 = pixel_on_facade(33, 0.0)
    ents, warnings = entrances.place_entrances(facade_box(), [{"box": [x0, y0, x1, y1], "score": 0.5}], CAMERA, np.eye(4), FRAME)
    assert ents == [] and "did not land on the mesh" in warnings[0]


def test_default_entrance_sits_at_facade_front_center():
    e = entrances._default_entrance(facade_box())
    assert e["position"] == pytest.approx([0, 0, 5 + entrances.MARKER_OFFSET_M], abs=1e-3)
    assert e["facing"] == [0.0, 0.0, 1.0]
    assert e["source"] == "default" and e["confidence"] == "auto-low"


def test_same_door_merges_overlaps_and_containment():
    door = [461, 434, 510, 498]
    door_plus_fanlight = [445, 332, 524, 497]  # real pair from the flooded Burruss image
    assert entrances._same_door(door, door_plus_fanlight)
    assert not entrances._same_door(door, [700, 434, 750, 498])


def test_crop_frame_matches_the_mesh_models_input_square():
    alpha = np.zeros((600, 800), np.uint8)
    alpha[100:400, 200:700] = 255  # 500 x 300 building
    xc, yc, side = entrances.crop_frame(alpha)
    assert (xc, yc) == pytest.approx((449.5, 249.5))
    assert side == pytest.approx(499 / 0.85)


def test_markers_are_baked_as_unlit_glowing_geometry():
    box = facade_box()
    ent = entrances._default_entrance(box)
    glb = entrances.add_markers(box.export(file_type="glb"), [ent])
    doc = glb_doc(glb)
    names = {m.get("name"): m for m in doc["materials"]}
    for name in ("entrance_frame", "entrance_glow"):
        assert "KHR_materials_unlit" in names[name]["extensions"]
        assert names[name]["emissiveFactor"]  # fallback glow for renderers without the extension
    assert "KHR_materials_unlit" in doc["extensionsUsed"]
    assert struct.unpack("<I", glb[8:12])[0] == len(glb)
    scene = trimesh.load(io.BytesIO(glb), file_type="glb", force="scene")
    assert len(scene.geometry) == 3  # building + frame + glow panel
    assert scene.bounds[0][1] == pytest.approx(0, abs=1e-6)  # markers never dip below the ground
