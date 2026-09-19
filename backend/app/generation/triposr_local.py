"""TripoSR run locally: the quota-free last resort before the placeholder (spec 06).

The public TripoSR Space is down (its `torchmcubes` build fails) and the SF3D Space bills the
HF token's daily ZeroGPU quota, so this runs the same open TripoSR model (MIT) on this machine
instead: Apple-silicon MPS if available, else CPU. `torchmcubes` is swapped for PyMCubes, which
is the only thing that stopped the model from installing.

Setup (one time, ~1.7 GB of weights on first use, all under backend/.cache/):
  git clone --depth 1 https://github.com/VAST-AI-Research/TripoSR backend/.cache/vendor/TripoSR
  .venv/bin/pip install torch omegaconf einops transformers pymcubes
"""
import sys
import threading
import types

import numpy as np
from PIL import Image

from . import config

VENDOR_DIR = config.CACHE_DIR / "vendor" / "TripoSR"
MC_RESOLUTION = 256
FOREGROUND_RATIO = 0.85
MAX_FACES = 30000  # decimation target: ~100k raw faces is heavy on a map full of buildings

_model = None
_device = None
_load_lock = threading.Lock()
_run_lock = threading.Lock()  # one inference at a time: it saturates the GPU/CPU anyway


def available() -> str | None:
    """None if usable, else why not."""
    if not (VENDOR_DIR / "tsr" / "system.py").is_file():
        return f"TripoSR repo not found at {VENDOR_DIR}"
    try:
        import mcubes  # noqa: F401
        import torch  # noqa: F401
    except ImportError as e:
        return f"missing dependency: {e.name}"
    return None


def _install_mcubes_shim() -> None:
    """Provide the one `torchmcubes.marching_cubes` call TripoSR makes, backed by PyMCubes."""
    if "torchmcubes" in sys.modules:
        return
    import mcubes
    import torch

    def marching_cubes(volume, threshold):
        verts, faces = mcubes.marching_cubes(volume.detach().cpu().numpy(), threshold)
        # torchmcubes orders vertex coords (last axis, middle, first); TripoSR undoes that
        # with [..., [2, 1, 0]], so hand it the same order.
        verts = np.ascontiguousarray(verts[:, [2, 1, 0]], dtype=np.float32)
        return torch.from_numpy(verts), torch.from_numpy(faces.astype(np.int64))

    shim = types.ModuleType("torchmcubes")
    shim.marching_cubes = marching_cubes
    sys.modules["torchmcubes"] = shim


def _load():
    global _model, _device
    with _load_lock:
        if _model is None:
            _install_mcubes_shim()
            if str(VENDOR_DIR) not in sys.path:
                sys.path.insert(0, str(VENDOR_DIR))
            import torch
            from tsr.system import TSR

            _device = "mps" if torch.backends.mps.is_available() else "cpu"
            model = TSR.from_pretrained("stabilityai/TripoSR", config_name="config.yaml", weight_name="model.ckpt")
            model.renderer.set_chunk_size(8192)
            _model = model.to(_device)
    return _model, _device


def generate_glb(cutout: Image.Image) -> bytes:
    """RGBA cutout (transparent background) -> raw TripoSR mesh as .glb bytes (baked texture)."""
    import torch

    model, device = _load()  # also puts the vendored repo on sys.path
    from tsr.utils import resize_foreground

    img = resize_foreground(cutout.convert("RGBA"), FOREGROUND_RATIO)
    arr = np.asarray(img).astype(np.float32) / 255.0
    # TripoSR was trained on objects composited over mid-grey.
    arr = arr[:, :, :3] * arr[:, :, 3:4] + (1 - arr[:, :, 3:4]) * 0.5
    img = Image.fromarray((arr * 255.0).astype(np.uint8))
    with _run_lock, torch.no_grad():
        codes = model([img], device=device)
        mesh = model.extract_mesh(codes, True, resolution=MC_RESOLUTION)[0]
    return bake_vertex_colors(mesh).export(file_type="glb", include_normals=True)


def bake_vertex_colors(mesh, max_faces: int = MAX_FACES):
    """Vertex colors -> a small texture, because deck.gl's PBR shader ignores COLOR_0.

    Verified in the deck_check harness: TripoSR's vertex-colored mesh renders flat grey on the
    map. So: decimate (TripoSR emits ~100k faces), carry colors over from the nearest original
    vertex, then give every face its own 2x2 texel cell holding its average color and point all
    three of its UVs at that cell's center. Smooth vertex normals are kept.
    """
    import trimesh
    from scipy.spatial import cKDTree

    src_colors = np.asarray(mesh.visual.vertex_colors, dtype=np.float32)[:, :3]
    if len(mesh.faces) > max_faces:
        decimated = mesh.simplify_quadric_decimation(face_count=max_faces)
        _, nearest = cKDTree(mesh.vertices).query(decimated.vertices)
        mesh, colors = decimated, src_colors[nearest]
    else:
        colors = src_colors
    faces = np.asarray(mesh.faces)
    normals = np.asarray(mesh.vertex_normals)[faces].reshape(-1, 3)
    face_rgb = colors[faces].mean(axis=1).clip(0, 255).astype(np.uint8)

    cells = int(np.ceil(np.sqrt(len(faces))))
    size = 1 << int(np.ceil(np.log2(cells * 2)))  # power-of-two texture, 2x2 texels per face
    per_row = size // 2
    tex = np.zeros((size, size, 3), dtype=np.uint8)
    idx = np.arange(len(faces))
    row, col = idx // per_row, idx % per_row
    for dy in (0, 1):
        for dx in (0, 1):
            tex[row * 2 + dy, col * 2 + dx] = face_rgb
    # Cell centers in UV space (glTF/trimesh: v = 0 at the bottom of the image).
    u = (col * 2 + 1) / size
    v = 1 - (row * 2 + 1) / size
    uv = np.repeat(np.stack([u, v], axis=1), 3, axis=0)

    baked = trimesh.Trimesh(
        vertices=np.asarray(mesh.vertices)[faces].reshape(-1, 3),
        faces=np.arange(len(faces) * 3).reshape(-1, 3),
        vertex_normals=normals,
        process=False,
    )
    baked.visual = trimesh.visual.TextureVisuals(
        uv=uv,
        material=trimesh.visual.material.PBRMaterial(
            baseColorTexture=Image.fromarray(tex), metallicFactor=0.0, roughnessFactor=0.9
        ),
    )
    return baked
