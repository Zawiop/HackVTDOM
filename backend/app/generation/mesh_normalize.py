"""normalizeMesh (spec: markdown_files/07-mesh-normalize.md).

Output convention for every mesh this backend returns (what steps 08/12 can rely on):
  * glTF 2.0 standard axes: +Y is up, the photographed facade faces +Z, and +X is the
    viewer's right when standing in front of the facade (so the photo is not mirrored)
  * units are meters
  * origin/pivot is at base-center: bounding-box center in X/Z, lowest point at y = 0
With deck.gl ScenegraphLayer, getOrientation [0, yaw, 90] stands such a mesh upright
(roll 90 maps glTF +Y to world up); at yaw 0 the facade faces south and the facade's
compass bearing is (180 - yaw) degrees.
"""
import io
import json
import math
import struct

import numpy as np
import trimesh

from . import config

ORIENTATION_NOTE = "glTF +Y up; facade faces +Z; meters; origin at base-center (y=0 is ground)"

# How each mesh source lays out its raw output. "front" = direction the photographed facade faces.
SOURCE_CONVENTIONS = {
    # Verified: file 06 CAPTURED EXAMPLE + SF3D's export code (Rx(-90) then Ry(+90) from a
    # Z-up frame whose conditioning camera is on +X) + a render of the real output.
    "sf3d": {"up": "+Y", "front": "-Z", "units": "normalized"},
    # Verified: TripoSR's camera code says "x back, y right, z up" with the input-view camera at
    # azimuth 0 = +X (tsr/utils.py get_spherical_cameras), and the repo exports raw, unrotated.
    "triposr-local": {"up": "+Z", "front": "+X", "units": "normalized"},
    # Our own procedural stand-in (assets/placeholder.glb), authored in glTF convention.
    "placeholder": {"up": "+Y", "front": "+Z", "units": "normalized"},
    # Hunyuan3D-2mv exports glTF-standard axes with the `mv_image_front` view facing +Z,
    # confirmed by rendering its output against a ground plane. Unit-normalized like the
    # others: its bounds come back at roughly [-1, 1], so it is fitted to the footprint.
    "hunyuan3d-mv": {"up": "+Y", "front": "+Z", "units": "normalized"},
}
# Anything else is assumed to follow the glTF 2.0 spec defaults.
DEFAULT_CONVENTION = {"up": "+Y", "front": "+Z", "units": "meters"}

_AXES = {
    "+X": (1, 0, 0), "-X": (-1, 0, 0),
    "+Y": (0, 1, 0), "-Y": (0, -1, 0),
    "+Z": (0, 0, 1), "-Z": (0, 0, -1),
}
# Candidate unit conversions tried when a "meters" mesh is badly off from the footprint.
_UNIT_FACTORS = {"centimeters": 0.01, "millimeters": 0.001, "inches": 0.0254, "feet": 0.3048}
UNIT_TOLERANCE = 3.5  # spec: "off by more than ~3-4x" = a units problem
# A unit correction is only trusted if it lands much closer than that; otherwise it's a guess.
UNIT_FACTOR_TOLERANCE = 2.0
MIN_COMPONENT_FACE_FRACTION = 0.005


def _rotation_between(a, b) -> np.ndarray:
    """4x4 rotation taking unit vector a onto unit vector b (handles the antiparallel case)."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    if np.allclose(a, b):
        return np.eye(4)
    if np.allclose(a, -b):
        perp = np.array([1.0, 0, 0]) if abs(a[0]) < 0.9 else np.array([0, 0, 1.0])
        return trimesh.transformations.rotation_matrix(math.pi, perp)
    return trimesh.geometry.align_vectors(a, b)


def _load_mesh(glb: bytes) -> trimesh.Trimesh:
    scene = trimesh.load(io.BytesIO(glb), file_type="glb", force="scene")
    if not scene.geometry:
        raise ValueError("mesh file has no geometry")
    # Bake node transforms into one mesh so bounds and later transforms are unambiguous.
    mesh = scene.to_geometry()
    if len(mesh.faces) == 0:
        raise ValueError("mesh has no faces")
    return mesh


def _drop_fragments(mesh: trimesh.Trimesh) -> tuple[trimesh.Trimesh, int]:
    """Remove tiny disconnected islands (floaters) that would skew bounds and the base.

    Connectivity is measured on a position-welded copy: generated meshes duplicate
    vertices along UV seams, so a plain split() would treat every texture island as a
    separate "fragment" and punch holes in the real surface.
    """
    welded = trimesh.Trimesh(mesh.vertices.copy(), mesh.faces.copy(), process=False)
    welded.merge_vertices(merge_tex=True, merge_norm=True)
    components = trimesh.graph.connected_components(welded.face_adjacency, nodes=np.arange(len(welded.faces)))
    if len(components) <= 1:
        return mesh, 0
    min_faces = MIN_COMPONENT_FACE_FRACTION * len(mesh.faces)
    keep = np.zeros(len(mesh.faces), dtype=bool)
    dropped = 0
    for comp in components:
        if len(comp) >= min_faces:
            keep[comp] = True
        else:
            dropped += 1
    if not keep.any():
        return mesh, 0
    mesh = mesh.copy()
    mesh.update_faces(keep)
    mesh.remove_unreferenced_vertices()
    return mesh, dropped


def _square_up_yaw(mesh: trimesh.Trimesh) -> float:
    """Yaw (radians, |yaw| <= 45 deg) that axis-aligns the mesh's minimum-area ground rectangle.

    A photo taken at a 3/4 angle yields a mesh whose walls sit diagonally in X/Z. Squaring
    it up keeps extents honest (width/depth instead of a diagonal) and lets step 08's
    0/90/180/270 rotation candidates line up with real walls. The smallest rotation is used
    so the photographed facade keeps facing +Z.
    """
    from scipy.spatial import ConvexHull

    pts = mesh.vertices[:, [0, 2]]
    try:
        hull = pts[ConvexHull(pts).vertices]
    except Exception:  # degenerate (flat/linear) outline: nothing to align
        return 0.0
    best_area, best_angle = math.inf, 0.0
    for p, q in zip(hull, np.roll(hull, -1, axis=0)):
        a = math.atan2(q[1] - p[1], q[0] - p[0])
        c, s = math.cos(a), math.sin(a)
        rotated = pts @ np.array([[c, -s], [s, c]])  # into the edge-aligned frame
        area = np.ptp(rotated[:, 0]) * np.ptp(rotated[:, 1])
        if area < best_area:
            best_area, best_angle = area, a
    # Rectangle axes are best_angle + k*90deg; pick the representative in (-45, 45].
    yaw = (best_angle + math.pi / 4) % (math.pi / 2) - math.pi / 4
    return yaw


def rewrite_glb_json(glb: bytes, mutate) -> bytes:
    """Edit a .glb's JSON chunk in place (mutate(doc) -> bool changed); the BIN chunk is untouched.

    For glTF features trimesh can't express on export (default materials, extensions).
    """
    json_len = struct.unpack("<I", glb[12:16])[0]
    doc = json.loads(glb[20 : 20 + json_len])
    if not mutate(doc):
        return glb
    chunk = json.dumps(doc, separators=(",", ":")).encode()
    chunk += b" " * (-len(chunk) % 4)  # GLB chunks are 4-byte aligned; JSON pads with spaces
    rest = glb[20 + json_len :]
    total = 12 + 8 + len(chunk) + len(rest)
    return glb[:8] + struct.pack("<I", total) + struct.pack("<I", len(chunk)) + b"JSON" + chunk + rest


def _ensure_material(glb: bytes) -> bytes:
    """Give material-less primitives a neutral PBR material.

    Vertex-colored meshes (local TripoSR) export with no material, and deck.gl's
    ScenegraphLayer then draws nothing at all (verified in the deck_check harness). A white
    baseColor keeps COLOR_0 as the visible color, per the glTF spec (baseColor x COLOR_0).
    """

    def mutate(doc):
        prims = [p for m in doc.get("meshes", []) for p in m["primitives"] if "material" not in p]
        if not prims:
            return False
        doc.setdefault("materials", []).append({
            "name": "vertex_color_default",
            "pbrMetallicRoughness": {"baseColorFactor": [1, 1, 1, 1], "metallicFactor": 0.0, "roughnessFactor": 0.9},
        })
        for p in prims:
            p["material"] = len(doc["materials"]) - 1
        return True

    return rewrite_glb_json(glb, mutate)


def normalize_glb(
    glb: bytes,
    source: str,
    footprint_width_m: float | None = None,
    footprint_depth_m: float | None = None,
) -> tuple[bytes, dict]:
    conv = SOURCE_CONVENTIONS.get(source, DEFAULT_CONVENTION)
    warnings: list[str] = []
    low = False
    if source not in SOURCE_CONVENTIONS:
        warnings.append(f"unknown mesh source {source!r}: assuming glTF defaults (+Y up, front +Z, meters)")

    mesh = _load_mesh(glb)
    mesh, dropped = _drop_fragments(mesh)

    # 1+2. Axes: bring the source's up axis to +Y, then yaw so the facade faces +Z.
    r_up = _rotation_between(_AXES[conv["up"]], (0, 1, 0))
    front = r_up[:3, :3] @ np.array(_AXES[conv["front"]], float)
    yaw = -math.atan2(front[0], front[2])
    r_front = trimesh.transformations.rotation_matrix(yaw, (0, 1, 0))
    mesh.apply_transform(r_front @ r_up)
    yaw_deg = round(math.degrees(yaw)) % 360

    # 2b. Square the ground outline up with X/Z (photos are rarely taken head-on).
    align = _square_up_yaw(mesh)
    r_align = trimesh.transformations.rotation_matrix(align, (0, 1, 0))
    mesh.apply_transform(r_align)

    # 3. Units, checked against the known footprint (or a default size when it's not known yet).
    ext = mesh.extents  # x = facade width, y = height, z = depth
    horiz = float(max(ext[0], ext[2]))
    footprint_known = bool(footprint_width_m and footprint_depth_m)
    if footprint_known:
        target = float(max(footprint_width_m, footprint_depth_m))
    else:
        target = config.DEFAULT_FOOTPRINT_M
        warnings.append(
            f"no footprint supplied: sized to a default {target:.0f} m; step 08 must rescale to the real footprint"
        )

    if conv["units"] == "normalized":
        # Image-to-3D models emit a unitless ~1-unit box; the only meaningful scale is the footprint.
        scale = target / horiz
        units = {"source": "normalized (unitless)", "method": f"fit longest horizontal side to {target:.2f} m"}
    else:
        ratio = horiz / target
        if 1 / UNIT_TOLERANCE <= ratio <= UNIT_TOLERANCE:
            scale = 1.0
            units = {"source": "meters", "method": f"within {UNIT_TOLERANCE}x of footprint ({ratio:.2f}x), unchanged"}
        else:
            best = min(_UNIT_FACTORS.items(), key=lambda kv: abs(math.log(horiz * kv[1] / target)))
            if abs(math.log(horiz * best[1] / target)) <= math.log(UNIT_FACTOR_TOLERANCE):
                scale = best[1]
                units = {"source": best[0], "method": f"{ratio:.1f}x off footprint; converted {best[0]} -> meters"}
            else:
                # No obvious unit mistake: don't guess a factor (spec 07 failure handling).
                scale = 1.0
                low = True
                units = {"source": "unknown", "method": f"{ratio:.1f}x off footprint, no unit factor fits; left unscaled"}
                warnings.append("unit sanity check failed: mesh size inconsistent with footprint, needs manual correction")
    mesh.apply_scale(scale)
    s_mat = np.diag([scale, scale, scale, 1.0])

    # 4. Pivot: base-center.
    lo, hi = mesh.bounds
    shift = [-(lo[0] + hi[0]) / 2, -lo[1], -(lo[2] + hi[2]) / 2]
    mesh.apply_translation(shift)
    # Raw file coordinates -> normalized meters, so anything located in the raw frame (e.g. the
    # mesh model's camera, for entrance detection) can follow the mesh.
    transform = trimesh.transformations.translation_matrix(shift) @ s_mat @ r_align @ r_front @ r_up

    ext = mesh.extents
    width, height, depth = float(ext[0]), float(ext[1]), float(ext[2])
    if not 2 <= height <= 200:
        low = True
        warnings.append(f"implausible building height after normalization: {height:.1f} m")
    if footprint_known:
        mesh_aspect = max(width, depth) / max(min(width, depth), 1e-6)
        fp_aspect = max(footprint_width_m, footprint_depth_m) / max(min(footprint_width_m, footprint_depth_m), 1e-6)
        if max(mesh_aspect / fp_aspect, fp_aspect / mesh_aspect) > 3:
            warnings.append(
                f"mesh aspect {mesh_aspect:.1f}:1 vs footprint {fp_aspect:.1f}:1 - single-view depth is a guess"
            )

    # NORMAL is required: without it luma.gl falls back to flat geometric normals (spec 12 note).
    out = _ensure_material(mesh.export(file_type="glb", include_normals=True))
    report = {
        "source": source,
        "convention": ORIENTATION_NOTE,
        "upAxis": {"from": conv["up"], "rotated": not np.allclose(r_up, np.eye(4))},
        "front": {"from": conv["front"], "yawDegrees": yaw_deg},
        "squareUpYawDegrees": round(math.degrees(align), 1),
        "units": {**units, "scale": round(float(scale), 4)},
        "pivot": "base-center",
        "extentsMeters": {"width": round(width, 2), "depth": round(depth, 2), "height": round(height, 2)},
        "footprint": {
            "widthMeters": footprint_width_m,
            "depthMeters": footprint_depth_m,
            "assumed": not footprint_known,
        },
        "removedFragments": dropped,
        "transform": np.round(transform, 6).tolist(),
        "faces": int(len(mesh.faces)),
        "confidence": "auto-low" if low else "auto-high",
        "warnings": warnings,
    }
    return out, report
