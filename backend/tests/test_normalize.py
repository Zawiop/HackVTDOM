"""normalizeMesh (spec 07) against real and synthetic meshes. Offline, no network.

Run from backend/: .venv/bin/pytest tests/test_normalize.py -q
"""
import io
import json
import math
import struct
from pathlib import Path

import numpy as np
import pytest
import trimesh

from app.generation import config
from app.generation.mesh_normalize import normalize_glb

FIXTURES = Path(__file__).parent / "fixtures"


def glb_attributes(glb: bytes) -> set:
    n = struct.unpack("<I", glb[12:16])[0]
    doc = json.loads(glb[20 : 20 + n])
    return {a for m in doc["meshes"] for p in m["primitives"] for a in p["attributes"]}


def load(glb: bytes) -> trimesh.Trimesh:
    return trimesh.load(io.BytesIO(glb), file_type="glb", force="scene").to_geometry()


def assert_base_centered(mesh: trimesh.Trimesh):
    lo, hi = mesh.bounds
    assert lo[1] == pytest.approx(0, abs=1e-4), "base must sit at y=0"
    assert (lo[0] + hi[0]) / 2 == pytest.approx(0, abs=1e-4)
    assert (lo[2] + hi[2]) / 2 == pytest.approx(0, abs=1e-4)


def building(width=40.0, height=12.0, depth=10.0, tower_front=True) -> trimesh.Trimesh:
    """A block with a tower stuck on its +Z side, so 'front' is detectable after transforms."""
    body = trimesh.creation.box(extents=[width, height, depth])
    body.apply_translation([0, height / 2, 0])
    tower = trimesh.creation.box(extents=[4, height * 1.8, 4])
    tower.apply_translation([0, height * 0.9, depth / 2 + 2 if tower_front else -(depth / 2 + 2)])
    return trimesh.util.concatenate([body, tower])


def tower_side(mesh: trimesh.Trimesh) -> float:
    """Z of the tallest vertices' centroid: > 0 means the tower is on the +Z (front) side."""
    v = mesh.vertices
    top = v[v[:, 1] > v[:, 1].max() - 0.5]
    return float(top[:, 2].mean())


def test_real_sf3d_capture_is_upright_front_facing_and_fitted():
    raw = (FIXTURES / "sf3d_raw.glb").read_bytes()  # the real mesh captured in file 06
    glb, rep = normalize_glb(raw, "sf3d", 95.0, 40.0)
    mesh = load(glb)
    assert_base_centered(mesh)
    assert rep["front"]["yawDegrees"] == 180  # SF3D facade faces -Z -> turned to +Z
    assert max(rep["extentsMeters"]["width"], rep["extentsMeters"]["depth"]) == pytest.approx(95.0, rel=1e-3)
    assert rep["confidence"] == "auto-high"
    # Texture survives the round trip (deck.gl needs it to look like the photo).
    assert isinstance(mesh.visual, trimesh.visual.TextureVisuals)
    assert mesh.visual.uv is not None and len(mesh.visual.uv) == len(mesh.vertices)
    # Seam-aware cleanup must not shred the surface.
    assert rep["faces"] > 0.95 * len(load(raw).faces)
    # deck.gl/luma.gl shades flat without NORMAL (spec 12 note), so it must be exported.
    assert glb_attributes(glb) >= {"POSITION", "NORMAL", "TEXCOORD_0"}


def test_sf3d_convention_turns_facade_to_plus_z():
    # Author a building the way SF3D exports it: +Y up, facade (tower) toward -Z.
    b = building(tower_front=False)
    glb, rep = normalize_glb(b.export(file_type="glb"), "sf3d", 40.0, 10.0)
    assert tower_side(load(glb)) > 0


def test_z_up_source_is_stood_upright(monkeypatch):
    from app.generation import mesh_normalize

    monkeypatch.setitem(mesh_normalize.SOURCE_CONVENTIONS, "zup", {"up": "+Z", "front": "-Y", "units": "meters"})
    b = building()
    # Convert the Y-up building to Z-up (tower/front -> -Y).
    b.apply_transform(trimesh.transformations.rotation_matrix(math.pi / 2, (1, 0, 0)))
    assert b.extents[2] > b.extents[1]  # really lying in Z now
    glb, rep = normalize_glb(b.export(file_type="glb"), "zup", 40.0, 10.0)
    mesh = load(glb)
    assert rep["upAxis"]["rotated"] is True
    assert mesh.extents[1] == pytest.approx(12 * 1.8, rel=1e-3)  # tower height is vertical again
    assert tower_side(mesh) > 0
    assert_base_centered(mesh)


def test_diagonal_mesh_is_squared_up():
    b = building()
    b.apply_transform(trimesh.transformations.rotation_matrix(math.radians(30), (0, 1, 0)))
    glb, rep = normalize_glb(b.export(file_type="glb"), "unknown-meters", 40.0, 14.0)
    mesh = load(glb)
    assert abs(rep["squareUpYawDegrees"]) == pytest.approx(30, abs=0.5)
    assert mesh.extents[0] == pytest.approx(40, rel=1e-3)
    assert tower_side(mesh) > 0  # smallest rotation keeps the facade at +Z


def test_meters_mesh_left_alone_when_consistent():
    glb, rep = normalize_glb(building().export(file_type="glb"), "custom", 42.0, 12.0)
    assert rep["units"]["scale"] == 1.0
    assert rep["units"]["source"] == "meters"
    assert rep["confidence"] == "auto-high"


def test_centimeter_mesh_is_converted():
    b = building()
    b.apply_scale(100)  # 40 m authored in cm = 4000 units
    glb, rep = normalize_glb(b.export(file_type="glb"), "custom", 40.0, 14.0)
    assert rep["units"]["source"] == "centimeters"
    assert load(glb).extents[0] == pytest.approx(40, rel=1e-3)
    assert rep["confidence"] == "auto-high"


def test_nonsense_scale_is_flagged_not_guessed():
    b = building()
    b.apply_scale(8)  # 8x: no cm/mm/in/ft factor lands within 2x of the footprint
    glb, rep = normalize_glb(b.export(file_type="glb"), "custom", 40.0, 14.0)
    assert rep["confidence"] == "auto-low"
    assert rep["units"]["scale"] == 1.0
    assert any("unit sanity check failed" in w for w in rep["warnings"])


def test_no_footprint_uses_default_and_says_so():
    glb, rep = normalize_glb(config.PLACEHOLDER_GLB.read_bytes(), "placeholder")
    assert rep["footprint"]["assumed"] is True
    assert max(rep["extentsMeters"]["width"], rep["extentsMeters"]["depth"]) == pytest.approx(config.DEFAULT_FOOTPRINT_M, rel=1e-3)
    assert any("no footprint supplied" in w for w in rep["warnings"])


def test_floaters_removed_and_base_not_dragged_down():
    b = building().subdivide().subdivide().subdivide().subdivide()  # realistic face count
    speck = trimesh.creation.box(extents=[0.2, 0.2, 0.2])
    speck.apply_translation([0, -5, 0])  # stray fragment below ground
    glb, rep = normalize_glb(trimesh.util.concatenate([b, speck]).export(file_type="glb"), "custom", 40.0, 14.0)
    assert rep["removedFragments"] == 1
    assert rep["extentsMeters"]["height"] == pytest.approx(12 * 1.8, rel=1e-3)


def test_placeholder_asset_is_committed_and_in_convention():
    assert config.PLACEHOLDER_GLB.is_file()
    mesh = load(config.PLACEHOLDER_GLB.read_bytes())
    assert glb_attributes(config.PLACEHOLDER_GLB.read_bytes()) >= {"POSITION", "NORMAL"}
    assert_base_centered(mesh)
    assert tower_side(mesh) > 0


def test_triposr_local_convention_stands_up_and_faces_front():
    # TripoSR's frame: +Z up, input camera (so the facade) on +X, image-right on +Y.
    b = building()  # Y-up, tower (front) at +Z, +X = viewer's right
    to_triposr = np.array([[0, 0, 1, 0], [1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0, 1]], float)  # x->y, y->z, z->x
    b.apply_transform(to_triposr)
    assert b.extents[2] == pytest.approx(12 * 1.8)  # height now along Z
    glb, rep = normalize_glb(b.export(file_type="glb"), "triposr-local", 40.0, 14.0)
    mesh = load(glb)
    assert mesh.extents[1] == pytest.approx(12 * 1.8, rel=1e-3)
    assert tower_side(mesh) > 0
    assert mesh.extents[0] == pytest.approx(40, rel=1e-3)  # facade length back on X, not mirrored into Z
    assert_base_centered(mesh)


def test_vertex_colored_mesh_gets_a_material():
    b = building()
    b.visual = trimesh.visual.ColorVisuals(b, vertex_colors=np.tile([200, 120, 60, 255], (len(b.vertices), 1)))
    raw = b.export(file_type="glb")
    n = struct.unpack("<I", raw[12:16])[0]
    assert "materials" not in json.loads(raw[20 : 20 + n])  # trimesh exports none: deck.gl draws nothing
    glb, _ = normalize_glb(raw, "custom", 40.0, 14.0)
    n = struct.unpack("<I", glb[12:16])[0]
    doc = json.loads(glb[20 : 20 + n])
    assert all("material" in p for m in doc["meshes"] for p in m["primitives"])
    assert struct.unpack("<I", glb[8:12])[0] == len(glb)  # GLB header length still consistent
    assert load(glb).faces.shape[0] > 0


def test_bake_vertex_colors_to_texture():
    from app.generation.triposr_local import bake_vertex_colors

    b = building().subdivide().subdivide().subdivide()  # ~1.5k faces
    b.visual = trimesh.visual.ColorVisuals(b, vertex_colors=np.tile([200, 120, 60, 255], (len(b.vertices), 1)))
    baked = bake_vertex_colors(b, max_faces=500)
    assert len(baked.faces) <= 500
    tex = np.asarray(baked.visual.material.baseColorTexture)
    uv = baked.visual.uv
    px = tex[((1 - uv[:, 1]) * tex.shape[0]).astype(int), (uv[:, 0] * tex.shape[1]).astype(int)]
    assert np.abs(px[:, :3].astype(int) - [200, 120, 60]).max() <= 1  # every face samples its color
    assert glb_attributes(baked.export(file_type="glb", include_normals=True)) >= {"POSITION", "NORMAL", "TEXCOORD_0"}
