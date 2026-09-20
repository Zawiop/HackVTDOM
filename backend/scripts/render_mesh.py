"""Render a .glb from several fixed views so orientation can be checked by eye.

Draws the mesh (colored from its texture/vertex colors) plus a translucent ground
plane at y=0 and labeled axes. Treats the file as glTF-standard: +Y is up.

Usage: .venv/bin/python scripts/render_mesh.py in.glb out.png [title]
"""
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import trimesh
from mpl_toolkits.mplot3d.art3d import Poly3DCollection


def face_colors(mesh: trimesh.Trimesh) -> np.ndarray:
    """Flat color shaded by a fixed light from above-front, so shape reads clearly."""
    light = np.array([0.3, 0.8, 0.5])
    light /= np.linalg.norm(light)
    shade = 0.35 + 0.65 * np.clip(mesh.face_normals @ light, 0, 1)
    return np.outer(shade, [0.85, 0.7, 0.5])


def render(path: str, out: str, title: str = "") -> None:
    scene = trimesh.load(path, force="scene")
    mesh = scene.to_geometry()
    # Render every triangle. Subsampling faces punches artificial holes into a
    # complete surface and makes this geometry-check preview misleading.
    v = mesh.vertices
    # glTF (x, y-up, z) -> matplotlib (x, -z, y) so "up" is up on screen.
    pts = np.column_stack([v[:, 0], -v[:, 2], v[:, 1]])
    tris = pts[mesh.faces]
    fc = face_colors(mesh)

    lo, hi = pts.min(axis=0), pts.max(axis=0)
    span = (hi - lo).max() * 0.6
    mid = (hi + lo) / 2

    views = [("front (+Z toward viewer)", 0, -90), ("right side (+X toward viewer)", 0, 0), ("top-down", 90, -90), ("perspective", 25, -60)]
    fig = plt.figure(figsize=(20, 5.5))
    for i, (name, elev, azim) in enumerate(views):
        ax = fig.add_subplot(1, 4, i + 1, projection="3d")
        ax.add_collection3d(Poly3DCollection(tris, facecolors=fc, edgecolors="none", linewidths=0))
        g = span * 1.3
        gx, gy = np.meshgrid([mid[0] - g, mid[0] + g], [mid[1] - g, mid[1] + g])
        ax.plot_surface(gx, gy, np.zeros_like(gx), color="green", alpha=0.15)
        ax.quiver(0, 0, 0, span * 0.5, 0, 0, color="r")
        ax.quiver(0, 0, 0, 0, 0, span * 0.5, color="b")
        ax.text(span * 0.55, 0, 0, "+X", color="r")
        ax.text(0, 0, span * 0.55, "+Y(up)", color="b")
        ax.set_xlim(mid[0] - span, mid[0] + span)
        ax.set_ylim(mid[1] - span, mid[1] + span)
        ax.set_zlim(min(0, lo[2]) - span * 0.1, min(0, lo[2]) + 2 * span - span * 0.1)
        ax.set_box_aspect((1, 1, 1))
        ax.view_init(elev=elev, azim=azim)
        ax.set_title(name, fontsize=9)
        ax.set_xticks([]); ax.set_yticks([]); ax.set_zticks([])
    b = mesh.bounds
    fig.suptitle(f"{title}  bounds min={np.round(b[0], 2)} max={np.round(b[1], 2)}  (green = ground y=0)", fontsize=10)
    fig.tight_layout()
    fig.savefig(out, dpi=90)


if __name__ == "__main__":
    render(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "")
