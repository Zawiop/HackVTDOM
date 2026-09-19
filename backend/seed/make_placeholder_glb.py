"""Generate a known-geometry placeholder building as glTF 2.0 binary (.glb).

Why a custom mesh instead of a cube: step 12 has to confirm the ScenegraphLayer
`[pitch, yaw, roll]` convention actually stands a mesh upright and faces it the
right way. A cube is symmetric, so it can hide both errors. This shape is
asymmetric on all three axes:

  - footprint 10m (X, "width") x 6m (Z, "depth")  -> yaw errors are visible
  - 8m tall with a pitched roof ridge             -> up-axis errors are visible
  - a red marker block on the +Z face ("front")   -> 180-degree flips are visible

Pivot is at base-centre (x=0, z=0, y=0 at the ground), matching what step 07
normalises every real mesh to, so the placeholder and real meshes place
identically. glTF is Y-up by convention; deck.gl maps that to Z-up ground.
"""
from __future__ import annotations

import json
import math
import struct
from pathlib import Path

W, D, H = 10.0, 6.0, 8.0   # metres: width (X), depth (Z), wall height (Y)
RIDGE = 11.0               # roof ridge height (Y)

hw, hd = W / 2, D / 2

# 0-3 base, 4-7 eaves, 8-9 ridge (runs along X so the gable faces +/-Z)
positions = [
    (-hw, 0.0, -hd), (hw, 0.0, -hd), (hw, 0.0, hd), (-hw, 0.0, hd),
    (-hw, H, -hd), (hw, H, -hd), (hw, H, hd), (-hw, H, hd),
    (0.0, RIDGE, -hd), (0.0, RIDGE, hd),
]
# a small block marking the FRONT (+Z) face, so a 180-degree yaw error is obvious
fx, fy0, fy1, fz = 1.2, 0.0, 3.0, hd + 0.6
base_n = len(positions)
positions += [
    (-fx, fy0, hd), (fx, fy0, hd), (fx, fy1, hd), (-fx, fy1, hd),
    (-fx, fy0, fz), (fx, fy0, fz), (fx, fy1, fz), (-fx, fy1, fz),
]

def quad(a, b, c, d):
    return [a, b, c, a, c, d]

indices: list[int] = []
indices += quad(0, 1, 2, 3)          # floor
indices += quad(4, 5, 1, 0)          # -Z wall
indices += quad(5, 6, 2, 1)          # +X wall
indices += quad(6, 7, 3, 2)          # +Z wall (front)
indices += quad(7, 4, 0, 3)          # -X wall
indices += quad(4, 8, 9, 7)          # roof slope -X
indices += quad(8, 5, 6, 9)          # roof slope +X
indices += [4, 5, 8, 7, 9, 6]        # gable triangles
b = base_n
indices += quad(b + 4, b + 5, b + 6, b + 7)   # marker front
indices += quad(b + 0, b + 1, b + 5, b + 4)   # marker bottom
indices += quad(b + 3, b + 7, b + 6, b + 2)   # marker top
indices += quad(b + 1, b + 2, b + 6, b + 5)   # marker +X
indices += quad(b + 4, b + 7, b + 3, b + 0)   # marker -X

# Flat shading: give every triangle its own three vertices so each can carry the
# face normal. Without NORMAL, luma.gl warns and falls back to derived normals,
# which makes every wall the same flat grey and hides the roof pitch entirely.
def _normal(a, b, c):
    u = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    v = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
    ln = math.sqrt(sum(x * x for x in n)) or 1.0
    return (n[0] / ln, n[1] / ln, n[2] / ln)


flat_pos: list[tuple[float, float, float]] = []
flat_nrm: list[tuple[float, float, float]] = []
for t in range(0, len(indices), 3):
    tri = [positions[indices[t + k]] for k in range(3)]
    n = _normal(*tri)
    flat_pos.extend(tri)
    flat_nrm.extend([n, n, n])

flat_idx = list(range(len(flat_pos)))

pos_bytes = b"".join(struct.pack("<3f", *p) for p in flat_pos)
nrm_bytes = b"".join(struct.pack("<3f", *n) for n in flat_nrm)
idx_bytes = b"".join(struct.pack("<H", i) for i in flat_idx)
while len(idx_bytes) % 4:
    idx_bytes += b"\x00"

buf = pos_bytes + nrm_bytes + idx_bytes
mins = [min(p[i] for p in flat_pos) for i in range(3)]
maxs = [max(p[i] for p in flat_pos) for i in range(3)]

gltf = {
    "asset": {"version": "2.0", "generator": "scorched-nebraska placeholder"},
    "scene": 0,
    "scenes": [{"nodes": [0]}],
    "nodes": [{"mesh": 0, "name": "placeholder_building"}],
    "meshes": [{
        "name": "placeholder_building",
        "primitives": [
            {"attributes": {"POSITION": 0, "NORMAL": 1}, "indices": 2, "material": 0}
        ],
    }],
    "materials": [{
        "name": "concrete",
        "pbrMetallicRoughness": {
            "baseColorFactor": [0.62, 0.60, 0.53, 1.0],
            "metallicFactor": 0.0, "roughnessFactor": 0.9,
        },
        "doubleSided": True,
    }],
    "accessors": [
        {"bufferView": 0, "componentType": 5126, "count": len(flat_pos),
         "type": "VEC3", "min": mins, "max": maxs},
        {"bufferView": 1, "componentType": 5126, "count": len(flat_nrm), "type": "VEC3"},
        {"bufferView": 2, "componentType": 5123, "count": len(flat_idx), "type": "SCALAR"},
    ],
    "bufferViews": [
        {"buffer": 0, "byteOffset": 0, "byteLength": len(pos_bytes), "target": 34962},
        {"buffer": 0, "byteOffset": len(pos_bytes), "byteLength": len(nrm_bytes),
         "target": 34962},
        {"buffer": 0, "byteOffset": len(pos_bytes) + len(nrm_bytes),
         "byteLength": len(idx_bytes), "target": 34963},
    ],
    "buffers": [{"byteLength": len(buf)}],
}

json_chunk = json.dumps(gltf, separators=(",", ":")).encode()
while len(json_chunk) % 4:
    json_chunk += b" "
bin_chunk = buf
while len(bin_chunk) % 4:
    bin_chunk += b"\x00"

glb = b"glTF" + struct.pack("<II", 2, 12 + 8 + len(json_chunk) + 8 + len(bin_chunk))
glb += struct.pack("<II", len(json_chunk), 0x4E4F534A) + json_chunk
glb += struct.pack("<II", len(bin_chunk), 0x004E4942) + bin_chunk

if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent.parent / "frontend" / "public" / "placeholder.glb"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(glb)
    print(f"wrote {out} ({len(glb)} bytes)")
    print(f"footprint {W}m x {D}m, ridge {RIDGE}m, pivot at base-centre, Y-up")
