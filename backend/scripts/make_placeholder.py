"""Generate backend/assets/placeholder.glb — the hard fallback mesh (spec file 06).

A low-poly ruined hall: long gabled block, a front tower, and a collapsed corner. Authored
in the backend's output convention: meters, glTF +Y up, facade toward +Z, origin at
base-center. It still goes through normalizeMesh so it gets sized to the real footprint.
Usage: .venv/bin/python scripts/make_placeholder.py
"""
from pathlib import Path

import numpy as np
import trimesh

OUT = Path(__file__).resolve().parent.parent / "assets" / "placeholder.glb"


def box(w, h, d, x=0.0, z=0.0, y=0.0):
    m = trimesh.creation.box(extents=[w, h, d])
    m.apply_translation([x, y + h / 2, z])
    return m


def gable_roof(w, d, rise, base_y):
    """Triangular prism, ridge running along x."""
    x0, x1 = -w / 2, w / 2
    verts = [
        (x0, base_y, -d / 2), (x0, base_y, d / 2), (x0, base_y + rise, 0),
        (x1, base_y, -d / 2), (x1, base_y, d / 2), (x1, base_y + rise, 0),
    ]
    faces = [(0, 1, 2), (3, 5, 4), (1, 4, 5), (1, 5, 2), (0, 2, 5), (0, 5, 3), (0, 3, 4), (0, 4, 1)]
    roof = trimesh.Trimesh(np.array(verts, float), np.array(faces))
    roof.fix_normals()
    return roof


parts = [
    box(18, 8, 9),                           # main hall
    gable_roof(18, 9, 3.2, 8),               # roof
    box(5, 15, 5, x=0, z=3.5),               # front tower
    box(1.2, 1.4, 1.2, x=-1.9, z=5.4, y=15),  # crenellations
    box(1.2, 1.4, 1.2, x=1.9, z=5.4, y=15),
    box(1.2, 1.4, 1.2, x=-1.9, z=1.6, y=15),
    box(1.2, 1.4, 1.2, x=1.9, z=1.6, y=15),
]
mesh = trimesh.util.concatenate(parts)
# Collapsed corner: shear the far-right top down so it reads as a ruin.
v = mesh.vertices
corner = (v[:, 0] > 6) & (v[:, 1] > 5)
v[corner, 1] -= (v[corner, 0] - 6) * 0.45
mesh.vertices = v

# Per-face vertices so exported normals are crisp face normals, not smoothed box corners.
mesh.unmerge_vertices()
lo, hi = mesh.bounds
mesh.apply_translation([-(lo[0] + hi[0]) / 2, -lo[1], -(lo[2] + hi[2]) / 2])
mesh.visual = trimesh.visual.TextureVisuals(
    material=trimesh.visual.material.PBRMaterial(
        name="placeholder_stone", baseColorFactor=[168, 142, 112, 255], metallicFactor=0.0, roughnessFactor=0.9
    )
)
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_bytes(mesh.export(file_type="glb", include_normals=True))
print(OUT, OUT.stat().st_size, "bytes, bounds", mesh.bounds.round(2).tolist())
