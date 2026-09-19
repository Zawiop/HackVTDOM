"""Fixtures and mesh builders for the step 08 placement tests.

The OSM polygons are real buildings around Virginia Tech, captured from the same
Overpass query step 02 issues and checked in so tests do not depend on a shared
public server being up. (c) OpenStreetMap contributors, ODbL.

The meshes are built from those polygons with a known rotation, scale and
vertical offset baked in, so "correct" means the transform recovers exactly what
was applied -- not that the output merely looked plausible.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import numpy as np
import trimesh

from app.services import placement_geom as g
from app.services.geo_math import polygon_centroid, to_local_meters

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@lru_cache(maxsize=1)
def _raw() -> Dict[str, Any]:
    return json.loads((FIXTURES / "osm_footprints.json").read_text())


@lru_cache(maxsize=1)
def all_buildings() -> Tuple[Dict[str, Any], ...]:
    """Every captured building, de-duplicated by OSM way id, in step 02's shape."""
    by_id: Dict[int, Dict[str, Any]] = {}
    for site in _raw().values():
        for way in site["elements"]:
            by_id[way["id"]] = {
                "osmId": way["id"],
                "tags": way.get("tags", {}),
                # GeoJSON order, matching FootprintCandidate.
                "geometry": [[p["lon"], p["lat"]] for p in way["geometry"]],
            }
    return tuple(by_id.values())


def building_named(name: str) -> Dict[str, Any]:
    for b in all_buildings():
        if b["tags"].get("name") == name:
            return b
    raise AssertionError(f"No fixture building named {name!r}")


def neighbors_of(target: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Everything except the named building -- step 02's neighbour list."""
    return [b for b in all_buildings() if b["osmId"] != target["osmId"]]


def local_ring(building: Dict[str, Any]) -> g.Ring:
    pts = [(p[0], p[1]) for p in building["geometry"]]
    return g.open_ring(to_local_meters(pts, polygon_centroid(pts)))


def centred_ring(building: Dict[str, Any]) -> g.Ring:
    ring = local_ring(building)
    cx, cy = g.centroid(ring)
    return [(x - cx, y - cy) for x, y in ring]


def extrude_to_glb(
    ring: Sequence[Tuple[float, float]],
    path: Path,
    height_meters: float = 20.0,
    pre_rotate_degrees: float = 0.0,
    pre_scale: float = 1.0,
    base_offset: float = 0.0,
) -> str:
    """Extrude a local (east, north) ring into step 07's convention.

    +Y up, meters, base at y = 0, and -- critically -- **east = +X, north = -Z**.
    glTF is right-handed, so mapping north to +Z instead would mirror the mesh,
    which silently costs IoU on any asymmetric building. Step 07's own note says
    the same thing from the other end: at yaw 0 the facade faces south, i.e. +Z
    points south.
    """
    r = g.rotate_ring(list(ring), pre_rotate_degrees)
    r = [(x * pre_scale, y * pre_scale) for x, y in r]
    h = height_meters * pre_scale
    n = len(r)

    verts = [(e, base_offset, -nn) for e, nn in r] + [(e, h + base_offset, -nn) for e, nn in r]
    faces: List[List[int]] = []
    for i in range(n):
        a, b = i, (i + 1) % n
        faces += [[a, b, b + n], [a, b + n, a + n]]
    for i in range(1, n - 1):  # roof cap, so the solid is closed enough to load
        faces.append([n, n + i, n + i + 1])

    mesh = trimesh.Trimesh(vertices=np.array(verts, dtype=float), faces=np.array(faces), process=False)
    mesh.export(path)
    return str(path)


def block_glb(
    path: Path,
    width_meters: float,
    depth_meters: float,
    height_meters: float,
    pre_rotate_degrees: float = 0.0,
) -> str:
    """A plain rectangular block, for tests that want a shape with no OSM quirks."""
    hw, hd = width_meters / 2, depth_meters / 2
    ring = [(-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd)]
    return extrude_to_glb(ring, path, height_meters, pre_rotate_degrees)


def prism_glb(path: Path, base_meters: float, depth_meters: float, height_meters: float) -> str:
    """A triangular prism: convex, but a poor match for any rectangular footprint."""
    ring = [(-base_meters / 2, -depth_meters / 2), (base_meters / 2, -depth_meters / 2), (0.0, depth_meters / 2)]
    return extrude_to_glb(ring, path, height_meters)


def angle_error(actual: float, expected: float) -> float:
    """Smallest separation, treating a 180-degree flip as the same alignment.

    A building footprint is very nearly centrosymmetric, so end-for-end is the
    same placement as far as the polygon is concerned.
    """
    d = abs(actual - expected) % 360.0
    return min(d, 360.0 - d, abs(d - 180.0))
