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


def colours_of(glb: bytes) -> np.ndarray:
    scene = trimesh.load(io.BytesIO(glb), file_type="glb", force="scene")
    mesh = trimesh.util.concatenate(list(scene.geometry.values()))
    return np.asarray(mesh.visual.vertex_colors)


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


def test_tinting_gives_an_untextured_mesh_vertex_colours():
    plain = a_box()
    scene = trimesh.load(io.BytesIO(plain), file_type="glb", force="scene")
    before = trimesh.util.concatenate(list(scene.geometry.values()))
    assert before.visual.kind != "vertex"

    tinted = tint_to_world_state(plain, "scorched")
    assert colours_of(tinted).shape[1] == 4


def test_each_world_state_gets_its_own_colour():
    states = ["scorched", "flooded", "reclaimed", "buried", "petrified"]
    means = {s: colours_of(tint_to_world_state(a_box(), s))[:, :3].mean(axis=0) for s in states}
    for a in states:
        for b in states:
            if a < b:
                assert np.abs(means[a] - means[b]).max() > 5, f"{a} and {b} tint alike"


def test_scorched_is_warm_and_flooded_is_cool():
    warm = colours_of(tint_to_world_state(a_box(), "scorched"))[:, :3].mean(axis=0)
    cool = colours_of(tint_to_world_state(a_box(), "flooded"))[:, :3].mean(axis=0)
    assert warm[0] > warm[2]
    assert cool[2] > cool[0]


def test_shading_varies_across_the_mesh_so_edges_still_read():
    # One flat colour on a 400k-face mesh hides every edge it has.
    cols = colours_of(tint_to_world_state(a_box(), "buried"))[:, :3]
    assert cols.std() > 1.0


def test_an_unknown_state_still_gets_a_usable_colour():
    cols = colours_of(tint_to_world_state(a_box(), "not-a-state"))
    assert cols.shape[1] == 4
    assert cols[:, :3].mean() > 0


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
