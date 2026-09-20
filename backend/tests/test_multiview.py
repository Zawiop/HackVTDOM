"""Multi-view reconstruction: the parts that do not need a GPU.

The live call is covered by the `live` marker; everything here is the
surrounding logic — which view combinations are accepted, and the tinting that
stands in for a texture the space cannot currently produce.
"""
from __future__ import annotations

import io

import numpy as np
import pytest
import trimesh

from app.generation.multiview import VIEWS, generate_multiview_mesh, tint_to_world_state
from app.generation.providers import ProviderError


def a_box() -> bytes:
    """A plain untextured box, standing in for the space's white_mesh.glb."""
    mesh = trimesh.creation.box(extents=(2.0, 1.0, 1.0))
    return trimesh.Scene(mesh).export(file_type="glb")


def body_of(glb: bytes) -> trimesh.Trimesh:
    """The building mesh, ignoring any baked entrance portals."""
    scene = trimesh.load(io.BytesIO(glb), file_type="glb", force="scene")
    bodies = [
        g for name, g in scene.geometry.items()
        if isinstance(g, trimesh.Trimesh) and not str(name).startswith("entrance_")
    ]
    return bodies[0]


def base_colour(glb: bytes) -> np.ndarray:
    """The material colour that actually reaches the renderer, 0-255.

    Asserted on rather than the vertex colours because a glTF PBR material
    ignores COLOR_0 unless it opts in — deck.gl showed the mesh plain grey when
    only vertex colours were set, so this is the value that matters.
    """
    mat = body_of(glb).visual.material
    raw = np.asarray(mat.baseColorFactor, dtype=float)[:3]
    # trimesh keeps this as 0-255 in memory and normalises to 0-1 on export.
    return raw if raw.max() > 1.0 else raw * 255.0


def shading_of(glb: bytes) -> np.ndarray:
    return np.asarray(body_of(glb).visual.vertex_attributes["color"])


def test_the_four_view_slots_are_the_ones_the_space_takes():
    assert VIEWS == ("front", "back", "left", "right")


def test_front_is_required():
    # Without it the model has no canonical view and the result comes back
    # rotated arbitrarily, which step 08 would then fit to the wrong bearing.
    with pytest.raises(ProviderError, match="front"):
        generate_multiview_mesh({"back": b"x", "left": b"y"}, deadline=1e9)


def test_a_single_view_is_refused_so_it_falls_back_to_the_cheaper_path():
    with pytest.raises(ProviderError, match="2 or more"):
        generate_multiview_mesh({"front": b"x"}, deadline=1e9)


def test_unknown_slot_names_do_not_count_towards_the_minimum():
    with pytest.raises(ProviderError, match="2 or more"):
        generate_multiview_mesh({"front": b"x", "above": b"y"}, deadline=1e9)


def test_empty_views_are_not_counted():
    with pytest.raises(ProviderError, match="2 or more"):
        generate_multiview_mesh({"front": b"x", "back": b""}, deadline=1e9)


def test_tints_are_dark_enough_to_survive_the_map_lighting():
    # The map runs ~1.9x total light gain, tuned for SF3D's dark baked textures.
    # A mid-tone base under that washes out to near-white, which is exactly how
    # the first version rendered: a grey building with a correct material.
    for state in ["scorched", "flooded", "reclaimed", "buried", "petrified"]:
        assert base_colour(tint_to_world_state(a_box(), state)).max() < 140


def test_tinting_gives_an_untextured_mesh_vertex_colours():
    plain = a_box()
    scene = trimesh.load(io.BytesIO(plain), file_type="glb", force="scene")
    before = trimesh.util.concatenate(list(scene.geometry.values()))
    assert before.visual.kind != "vertex"

    tinted = tint_to_world_state(plain, "scorched")
    assert shading_of(tinted).shape[1] == 4
    assert base_colour(tinted).max() > 0


def test_each_world_state_gets_its_own_colour():
    states = ["scorched", "flooded", "reclaimed", "buried", "petrified"]
    means = {s: base_colour(tint_to_world_state(a_box(), s)) for s in states}
    for a in states:
        for b in states:
            if a < b:
                assert np.abs(means[a] - means[b]).max() > 5, f"{a} and {b} tint alike"


def test_scorched_is_warm_and_flooded_is_cool():
    warm = base_colour(tint_to_world_state(a_box(), "scorched"))
    cool = base_colour(tint_to_world_state(a_box(), "flooded"))
    assert warm[0] > warm[2]
    assert cool[2] > cool[0]


def test_shading_varies_across_the_mesh_so_edges_still_read():
    # One flat colour on a 400k-face mesh hides every edge it has.
    cols = shading_of(tint_to_world_state(a_box(), "buried"))[:, :3]
    assert cols.std() > 1.0


def test_an_unknown_state_still_gets_a_usable_colour():
    assert base_colour(tint_to_world_state(a_box(), "not-a-state")).mean() > 0
    assert shading_of(tint_to_world_state(a_box(), "not-a-state")).shape[1] == 4


def test_a_mesh_with_no_triangles_is_returned_untouched():
    # A scene the loader accepts but that holds nothing to colour: hand it back
    # rather than inventing geometry for it.
    cloud = trimesh.PointCloud(np.random.default_rng(0).random((32, 3)))
    glb = trimesh.Scene(cloud).export(file_type="glb")
    assert tint_to_world_state(glb, "flooded") == glb


def test_unreadable_bytes_raise_rather_than_returning_a_broken_mesh():
    # Silently passing garbage through would put a corrupt .glb on the map with
    # no indication anything went wrong.
    with pytest.raises(Exception):
        tint_to_world_state(b"not a glb at all", "scorched")
