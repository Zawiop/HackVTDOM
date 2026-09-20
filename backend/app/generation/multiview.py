"""Multi-view reconstruction from several photos of the same building.

SF3D infers a whole building from one photograph, which means everything the
camera could not see is invention. Give a model four sides and the geometry
stops being a guess: `tencent/Hunyuan3D-2mv` takes front/back/left/right and
reconstructs from all of them.

Two things about this space are worth knowing before reading the code.

Its `/generation_all` endpoint — the one that also paints a texture — fails
server-side with a PyMeshLabException in about five seconds, on clean
background-removed input, every time. Only `/shape_generation` works, and that
returns `white_mesh.glb`: accurate geometry with no texture and no vertex
colours at all.

So this trades texture for geometry, and that trade is the reason it is opt-in
rather than the default. An untextured building would read as a grey blob on
the map, so the mesh is tinted to its own World State here — a scorched
building comes back ochre, a flooded one teal — which matches the ground it
stands in and looks deliberate rather than broken.
"""
from __future__ import annotations

import io
import tempfile
import time
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image

from . import config
from .providers import ProviderError, looks_like_quota

SPACE = "tencent/Hunyuan3D-2mv"
VIEWS = ("front", "back", "left", "right")

# Base colour per World State, lifted from the terrain palette so a building
# and the ground around it read as one place.
_TINTS: dict[str, tuple[int, int, int]] = {
    "scorched": (150, 104, 56),
    "flooded": (74, 116, 120),
    "reclaimed": (96, 122, 66),
    "buried": (188, 164, 122),
    "petrified": (140, 138, 134),
}
_DEFAULT_TINT = (156, 150, 140)


def _shade(mesh: trimesh.Trimesh, rgb: tuple[int, int, int]) -> np.ndarray:
    """Per-vertex colour: the state tint, lit from above so form still reads.

    A single flat colour on a 400k-face mesh hides every edge it has. Shading
    by the vertex normal's vertical component keeps roofs bright and walls
    darker, which is what makes the silhouette legible at map distance.
    """
    normals = np.asarray(mesh.vertex_normals, dtype=np.float32)
    up = np.clip(normals[:, 1], -1.0, 1.0)
    # 0.62 at a downward face, 1.18 straight up.
    factor = (0.9 + 0.28 * up)[:, None]
    base = np.array(rgb, dtype=np.float32)[None, :]
    lit = np.clip(base * factor, 0, 255).astype(np.uint8)
    alpha = np.full((len(lit), 1), 255, dtype=np.uint8)
    return np.hstack([lit, alpha])


def tint_to_world_state(glb: bytes, world_state: str | None) -> bytes:
    """Give an untextured mesh the colour of its World State."""
    scene = trimesh.load(io.BytesIO(glb), file_type="glb", force="scene")
    meshes = [m for m in scene.geometry.values() if isinstance(m, trimesh.Trimesh)]
    if not meshes:
        return glb
    mesh = trimesh.util.concatenate(meshes) if len(meshes) > 1 else meshes[0]
    rgb = _TINTS.get(world_state or "", _DEFAULT_TINT)
    mesh.visual = trimesh.visual.ColorVisuals(mesh=mesh, vertex_colors=_shade(mesh, rgb))
    return trimesh.Scene(mesh).export(file_type="glb")


def _as_png(data: bytes, path: Path) -> Path:
    """Hunyuan wants a cut-out subject; write whatever we were given as PNG."""
    img = Image.open(io.BytesIO(data))
    img.load()
    img.save(path, format="PNG")
    return path


def generate_multiview_mesh(
    views: dict[str, bytes],
    deadline: float,
    *,
    world_state: str | None = None,
) -> bytes:
    """Reconstruct from 2-4 labelled views. Returns tinted .glb bytes.

    `views` maps any of front/back/left/right to image bytes. Front is required
    — it is the only view the model treats as canonical, and without it the
    result comes back rotated arbitrarily.
    """
    supplied = {k: v for k, v in views.items() if k in VIEWS and v}
    if "front" not in supplied:
        raise ProviderError("hunyuan3d-mv", "multi-view needs at least a front view")
    if len(supplied) < 2:
        raise ProviderError("hunyuan3d-mv", "multi-view needs 2 or more views")

    from gradio_client import Client, handle_file

    with tempfile.TemporaryDirectory(dir=config.OUTPUT_DIR) as tmp:
        tmpdir = Path(tmp)
        paths = {
            name: _as_png(data, tmpdir / f"{name}.png") for name, data in supplied.items()
        }
        try:
            client = Client(SPACE, token=config.HF_TOKEN, verbose=False, download_files=tmp)
            job = client.submit(
                None,  # caption
                None,  # single-image slot, unused on the multi-view path
                handle_file(str(paths["front"])),
                handle_file(str(paths["back"])) if "back" in paths else None,
                handle_file(str(paths["left"])) if "left" in paths else None,
                handle_file(str(paths["right"])) if "right" in paths else None,
                5,      # steps
                5.0,    # guidance_scale
                1234,   # seed
                256,    # octree_resolution
                False,  # check_box_rembg — callers pass cut-outs already
                8000,   # num_chunks
                True,   # randomize_seed
                # NOT /generation_all: its texture stage raises PyMeshLabException
                # server-side on every input we have tried.
                api_name="/shape_generation",
            )
            result = job.result(timeout=max(1.0, deadline - time.monotonic()))
        except TimeoutError:
            raise
        except Exception as e:
            msg = str(e)[:300]
            raise ProviderError(
                "hunyuan3d-mv", f"{type(e).__name__}: {msg}", quota=looks_like_quota(msg)
            ) from None

        value = result[0] if isinstance(result, (list, tuple)) else result
        path = value.get("value") if isinstance(value, dict) else value
        if isinstance(path, dict):
            path = path.get("path")
        if not path or not Path(path).is_file():
            raise ProviderError("hunyuan3d-mv", f"no mesh in result: {result!r:.200}")

        raw = Path(path).read_bytes()

    return tint_to_world_state(raw, world_state)
