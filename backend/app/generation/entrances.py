"""Entrances: find the doors in the building image and mark them on the mesh.

1. Detect doors with OWLv2 (open-vocabulary, runs locally, no quota). "a window" is queried
   alongside the door phrases so windows are claimed as windows, not false doors.
2. Keep only door boxes that sit on the building (cutout alpha) and reach down near its base.
3. Replay the mesh model's own input crop + camera to turn each box into rays, carry the camera
   through normalization's raw->normalized transform, and raycast the normalized mesh.
4. Size the door from the hit depth, orient it by the facade normals around the hit, and bake a
   glowing portal (emissive frame + panel) onto the facade, a little proud of the wall.

Entrances are returned in the normalized mesh frame (meters, +Y up, facade toward +Z, y = 0 is
the ground), so they move with the mesh under step 08's transform. If no door is found, one
default entrance goes at the front-center of the facade, flagged `auto-low`.

Needs torch + transformers (backend/requirements-local-mesh.txt). Without them detection is
skipped with a warning and the default front-center entrance is used instead.
"""
import io
import math
import threading

import numpy as np
import trimesh
from PIL import Image

from .mesh_normalize import rewrite_glb_json

DETECTOR = "google/owlv2-base-patch16-ensemble"
DOOR_QUERIES = ["a door", "a doorway", "a building entrance", "an arched doorway"]
QUERIES = DOOR_QUERIES + ["a window"]  # windows compete for boxes instead of becoming doors
SCORE_THRESHOLD = 0.2
MAX_ENTRANCES = 4
FOREGROUND_RATIO = 0.85  # both SF3D and TripoSR crop the cutout to max(h, w) / 0.85, centered

# Each mesh model's input-view camera in its *raw* output frame (before normalization).
# SF3D: camera on +X of a Z-up frame, then its export applies Rx(-90), Ry(+90) (file 06) ->
#   camera at -Z looking +Z, up +Y, image-right -X. Distance/FOV from its gradio_app.py.
# TripoSR: "x back, y right, z up", input view at azimuth 0 = +X (tsr/utils.py). Distance/FOV
#   are its render defaults (tsr/system.py).
CAMERAS = {
    "sf3d": {"position": (0, 0, -1.6), "forward": (0, 0, 1), "up": (0, 1, 0), "right": (-1, 0, 0), "fovy": 40.0},
    "triposr-local": {"position": (1.9, 0, 0), "forward": (-1, 0, 0), "up": (0, 0, 1), "right": (0, 1, 0), "fovy": 40.0},
}

MARKER_OFFSET_M = 0.25  # in front of the most protruding wall surface around the door
MARKER_DEPTH_M = 0.3
_FRAME_MATERIAL = trimesh.visual.material.PBRMaterial(
    name="entrance_frame", baseColorFactor=[255, 214, 120, 255], emissiveFactor=[1.0, 0.72, 0.28],
    metallicFactor=0.0, roughnessFactor=0.6,
)
_PANEL_MATERIAL = trimesh.visual.material.PBRMaterial(
    name="entrance_glow", baseColorFactor=[255, 122, 0, 255], emissiveFactor=[1.0, 0.5, 0.08],
    metallicFactor=0.0, roughnessFactor=0.9,
)

_detector = None
_lock = threading.Lock()


def available() -> str | None:
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except ImportError as e:
        return f"entrance detection needs {e.name} (pip install -r requirements-local-mesh.txt)"
    return None


def _load():
    global _detector
    with _lock:
        if _detector is None:
            import torch
            from transformers import Owlv2ForObjectDetection, Owlv2Processor

            device = "mps" if torch.backends.mps.is_available() else "cpu"
            # use_fast=True would pull in torchvision for a processor we call twice a minute.
            processor = Owlv2Processor.from_pretrained(DETECTOR, use_fast=False)
            model = Owlv2ForObjectDetection.from_pretrained(DETECTOR).to(device).eval()
            _detector = (processor, model, device)
    return _detector


def warm() -> None:
    if available() is None:
        _load()


def _same_door(a, b) -> bool:
    """Boxes overlap a lot, or one mostly contains the other (e.g. door vs door + fanlight above)."""
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return inter / (area_a + area_b - inter) > 0.3 or inter / min(area_a, area_b) > 0.6


def detect_doors(image: Image.Image, alpha: np.ndarray) -> list[dict]:
    """Door boxes [x0, y0, x1, y1] in image pixels, best first, filtered to the building."""
    import torch

    processor, model, device = _load()
    rgb = image.convert("RGB")
    inputs = processor(text=[QUERIES], images=rgb, return_tensors="pt").to(device)
    with torch.no_grad():
        out = model(**inputs)
    side = max(rgb.size)  # OWLv2 pads to a square; boxes are relative to it
    # transformers renamed this for OWL models; the old name warns and goes away in v5.
    post_process = getattr(
        processor, "post_process_grounded_object_detection", processor.post_process_object_detection
    )
    res = post_process(
        out, threshold=SCORE_THRESHOLD, target_sizes=torch.tensor([[side, side]]).to(device)
    )[0]

    opaque = alpha > 127
    rows = np.where(opaque.any(axis=1))[0]
    if rows.size == 0:
        return []
    building_h = rows[-1] - rows[0] + 1
    candidates = []
    for score, label, box in zip(res["scores"].tolist(), res["labels"].tolist(), res["boxes"].tolist()):
        if QUERIES[label] not in DOOR_QUERIES:
            continue
        x0, y0, x1, y1 = (max(0, int(round(v))) for v in box)
        x1, y1 = min(x1, alpha.shape[1]), min(y1, alpha.shape[0])
        w, h = x1 - x0, y1 - y0
        if w < 4 or h < 4 or not 0.7 <= h / w <= 4.5:
            continue
        if opaque[y0:y1, x0:x1].mean() < 0.5:  # mostly background: not on this building
            continue
        cols = opaque[:, x0:x1]
        base = np.where(cols.any(axis=1))[0][-1]  # lowest building pixel under the door
        if base - y1 > 0.2 * building_h:  # floating high on the facade: a window, not a door
            continue
        candidates.append({"box": [x0, y0, x1, y1], "score": round(score, 3), "label": QUERIES[label]})
    candidates.sort(key=lambda c: -c["score"])
    kept: list[dict] = []
    for c in candidates:  # the four door phrases often box the same door
        if not any(_same_door(c["box"], k["box"]) for k in kept):
            kept.append(c)
    return kept[:MAX_ENTRANCES]


def crop_frame(alpha: np.ndarray) -> tuple[float, float, float]:
    """(x_center, y_center, side) of the square the mesh models actually saw, in image pixels."""
    ys, xs = np.where(alpha > 127)
    xc, yc = (xs.min() + xs.max()) / 2, (ys.min() + ys.max()) / 2
    side = max(xs.max() - xs.min(), ys.max() - ys.min()) / FOREGROUND_RATIO
    return float(xc), float(yc), float(side)


def _camera_in_mesh(camera: dict, transform: np.ndarray) -> dict:
    """Carry a raw-frame camera through normalization (rotation + uniform scale + shift)."""
    lin = transform[:3, :3]
    scale = float(np.cbrt(np.linalg.det(lin)))
    rot = lin / scale

    def unit(v):
        v = rot @ np.asarray(v, float)
        return v / np.linalg.norm(v)

    return {
        "origin": trimesh.transform_points([camera["position"]], transform)[0],
        "forward": unit(camera["forward"]),
        "up": unit(camera["up"]),
        "right": unit(camera["right"]),
        "tan": math.tan(math.radians(camera["fovy"]) / 2),
    }


def _rays(cam: dict, frame, pixels: np.ndarray) -> np.ndarray:
    xc, yc, side = frame
    u = (pixels[:, 0] - (xc - side / 2)) / side
    v = (pixels[:, 1] - (yc - side / 2)) / side
    a = (2 * u - 1) * cam["tan"]
    b = (1 - 2 * v) * cam["tan"]
    d = cam["forward"][None, :] + a[:, None] * cam["right"][None, :] + b[:, None] * cam["up"][None, :]
    return d / np.linalg.norm(d, axis=1, keepdims=True)


def _portal(width: float, height: float) -> tuple[trimesh.Trimesh, trimesh.Trimesh]:
    """Door-shaped frame + glowing panel in a local frame: x right, y up, +z out of the wall."""
    t = max(0.2, 0.12 * width)
    parts = []
    for cx in (-(width - t) / 2, (width - t) / 2):  # jambs
        jamb = trimesh.creation.box(extents=[t, height, MARKER_DEPTH_M])
        jamb.apply_translation([cx, height / 2, 0])
        parts.append(jamb)
    lintel = trimesh.creation.box(extents=[width, t, MARKER_DEPTH_M])
    lintel.apply_translation([0, height - t / 2, 0])
    parts.append(lintel)
    frame = trimesh.util.concatenate(parts)
    panel = trimesh.creation.box(extents=[max(width - 2 * t, 0.1), max(height - t, 0.1), MARKER_DEPTH_M * 0.4])
    panel.apply_translation([0, (height - t) / 2, -MARKER_DEPTH_M * 0.2])
    return frame, panel


def _default_entrance(mesh: trimesh.Trimesh) -> dict:
    """Front-center of the facade, where the building meets the ground."""
    lo, hi = mesh.bounds
    width = float(hi[0] - lo[0])
    y = min(2.0, 0.1 * float(hi[1]))
    origin = np.array([[0.0, y, hi[2] + 10.0]])
    hits, _, _ = mesh.ray.intersects_location(origin, np.array([[0.0, 0.0, -1.0]]), multiple_hits=False)
    z = float(hits[0][2]) if len(hits) else float(hi[2])
    door_w = float(np.clip(0.06 * width, 1.5, 4.0))
    return {
        "position": [0.0, 0.0, round(z + MARKER_OFFSET_M, 3)],
        "facing": [0.0, 0.0, 1.0],
        "widthMeters": round(door_w, 2),
        "heightMeters": round(float(np.clip(1.4 * door_w, 2.2, 0.8 * hi[1])), 2),
        "score": None,
        "imageBox": None,
        "source": "default",
        "confidence": "auto-low",
    }


def place_entrances(mesh: trimesh.Trimesh, detections: list[dict], camera: dict, transform, frame) -> tuple[list[dict], list[str]]:
    """Project detected door boxes onto the normalized mesh. Returns (entrances, warnings)."""
    cam = _camera_in_mesh(camera, np.asarray(transform, float))
    fwd_h = cam["forward"] * [1, 0, 1]
    fwd_h /= np.linalg.norm(fwd_h) or 1.0
    top = float(mesh.bounds[1][1])
    entrances, warnings = [], []
    for det in detections:
        x0, y0, x1, y1 = det["box"]
        gx, gy = np.meshgrid(np.linspace(x0, x1, 7)[1:-1], np.linspace(y0, y1, 7)[1:-1])
        pixels = np.column_stack([np.r_[(x0 + x1) / 2, gx.ravel()], np.r_[(y0 + y1) / 2, gy.ravel()]])
        dirs = _rays(cam, frame, pixels)
        origins = np.repeat(cam["origin"][None, :], len(dirs), axis=0)
        hits, ray_idx, tri_idx = mesh.ray.intersects_location(origins, dirs, multiple_hits=False)
        if len(hits) == 0:
            warnings.append(f"door at image box {det['box']} did not land on the mesh; skipped")
            continue
        center = hits[ray_idx == 0][0] if (ray_idx == 0).any() else hits.mean(axis=0)

        normal = mesh.face_normals[tri_idx].mean(axis=0) * [1, 0, 1]
        if np.linalg.norm(normal) < 1e-6 or np.dot(normal, -fwd_h) <= 0.2:
            normal = -fwd_h  # rough or back-facing surface: face the camera instead
        facing = normal / np.linalg.norm(normal)

        depth = float(np.dot(center - cam["origin"], cam["forward"]))
        xc, yc, side = frame
        width = (x1 - x0) / side * 2 * depth * cam["tan"]
        height = (y1 - y0) / side * 2 * depth * cam["tan"]
        bottom = float(center[1]) - height / 2
        if bottom < 0.5:
            bottom = 0.0  # doors stand on the ground; absorb small reconstruction error
        height = min(height, 0.9 * top - bottom)
        if width < 0.5 or height < 1.0:
            warnings.append(f"door at image box {det['box']} came out implausibly small; skipped")
            continue

        protrusion = max(0.0, float(np.max((hits - center) @ facing)))
        anchor = center + facing * (protrusion + MARKER_OFFSET_M)
        entrances.append({
            "position": [round(float(anchor[0]), 3), round(bottom, 3), round(float(anchor[2]), 3)],
            "facing": [round(float(facing[0]), 4), 0.0, round(float(facing[2]), 4)],
            "widthMeters": round(float(width), 2),
            "heightMeters": round(float(height), 2),
            "score": det["score"],
            "imageBox": det["box"],
            "source": "detected",
            "confidence": "auto-high",
        })
    return entrances, warnings


def add_markers(glb: bytes, entrances: list[dict]) -> bytes:
    """Bake a glowing portal per entrance into the normalized .glb, beside the building mesh."""
    scene = trimesh.load(io.BytesIO(glb), file_type="glb", force="scene")
    for i, e in enumerate(entrances):
        frame, panel = _portal(e["widthMeters"], e["heightMeters"])
        yaw = math.atan2(e["facing"][0], e["facing"][2])
        place = trimesh.transformations.translation_matrix(e["position"]) @ trimesh.transformations.rotation_matrix(yaw, (0, 1, 0))
        for part, material, name in ((frame, _FRAME_MATERIAL, "frame"), (panel, _PANEL_MATERIAL, "glow")):
            part = part.copy()
            part.unmerge_vertices()  # crisp flat-shaded box faces
            part.apply_transform(place)
            part.visual = trimesh.visual.TextureVisuals(material=material)
            scene.add_geometry(part, geom_name=f"entrance_{i}_{name}")
    return rewrite_glb_json(scene.export(file_type="glb", include_normals=True), _make_markers_unlit)


def _make_markers_unlit(doc) -> bool:
    """KHR_materials_unlit on the marker materials: full-brightness color whatever the lighting,
    which is what reads as "glowing" on the map. Renderers without it fall back to the
    emissive PBR material, per the extension spec."""
    changed = False
    for m in doc.get("materials", []):
        if m.get("name") in (_FRAME_MATERIAL.name, _PANEL_MATERIAL.name):
            m.setdefault("extensions", {})["KHR_materials_unlit"] = {}
            changed = True
    if changed and "KHR_materials_unlit" not in doc.setdefault("extensionsUsed", []):
        doc["extensionsUsed"].append("KHR_materials_unlit")
    return changed


def mark_entrances(glb: bytes, provider: str, transform, image: Image.Image, alpha: np.ndarray) -> tuple[bytes, list[dict], list[str]]:
    """Detect, project and bake. Returns (glb with markers, entrances, warnings)."""
    mesh = trimesh.load(io.BytesIO(glb), file_type="glb", force="scene").to_geometry()
    warnings: list[str] = []
    entrances: list[dict] = []
    camera = CAMERAS.get(provider)
    if camera is None:
        warnings.append(f"no camera model for {provider!r}: entrance placed at the facade front-center")
    elif (reason := available()) is not None:
        warnings.append(reason)
    else:
        detections = detect_doors(image, alpha)
        if detections:
            entrances, more = place_entrances(mesh, detections, camera, transform, crop_frame(alpha))
            warnings += more
        if not entrances:
            warnings.append("no door detected in the image: default entrance at the facade front-center (auto-low)")
    if not entrances:
        entrances = [_default_entrance(mesh)]
    for i, e in enumerate(entrances):
        e["id"] = i
        e["isMain"] = i == 0
    return add_markers(glb, entrances), entrances, warnings
