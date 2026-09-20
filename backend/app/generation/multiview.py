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
# Tuned against the map, not picked on a colour wheel. Two things constrain
# these: the LightingEffect runs about 1.9x total gain (ambient 1.05 + key 0.55
# + fill 0.3), tuned for the already-dark baked textures SF3D returns, so a
# mid-tone base washes out to near-white — the first attempt rendered a plain
# grey building despite a correct material. Going dark enough to survive that
# then sank the building into its own terrain, since the ground uses the same
# palette. These sit deliberately lighter than the matching terrain core so the
# building reads as standing *in* the state rather than dissolving into it.
_TINTS: dict[str, tuple[int, int, int]] = {
    "scorched": (112, 76, 42),
    "flooded": (56, 86, 92),
    "reclaimed": (70, 92, 48),
    "buried": (130, 112, 82),
    "petrified": (100, 99, 96),
}
_DEFAULT_TINT = (104, 100, 94)


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
    """Give an untextured mesh the colour of its World State.

    Node-aware on purpose. This runs at the very end of the mesh pipeline,
    after step 07 normalization (which rebuilds materials and would otherwise
    drop vertex colours) and after entrance marking (which bakes glowing amber
    portals in as extra nodes). Those portals already carry their own colour
    and must keep it, so anything that is already coloured or textured is left
    alone and the scene graph is preserved rather than concatenated.
    """
    scene = trimesh.load(io.BytesIO(glb), file_type="glb", force="scene")
    rgb = _TINTS.get(world_state or "", _DEFAULT_TINT)

    touched = False
    for name, geom in scene.geometry.items():
        if not isinstance(geom, trimesh.Trimesh) or not len(geom.faces):
            continue
        # Entrance portals are baked in with their own emissive colour.
        if str(name).startswith("entrance_"):
            continue
        visual = getattr(geom, "visual", None)
        if getattr(visual, "kind", None) in ("vertex", "face", "texture"):
            # Already carries colour of its own; do not overwrite it.
            if getattr(visual, "kind", None) == "texture" and _has_real_texture(visual):
                continue
        # Both, deliberately. Vertex colours carry the shading that keeps edges
        # readable, but a glTF PBR material ignores COLOR_0 unless it opts in —
        # deck.gl rendered the mesh plain grey with vertex colours alone. The
        # baseColorFactor is what actually shows up on the map.
        geom.visual = trimesh.visual.TextureVisuals(
            material=trimesh.visual.material.PBRMaterial(
                name=f"world-state-{world_state or 'neutral'}",
                baseColorFactor=[rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, 1.0],
                metallicFactor=0.0,
                roughnessFactor=0.85,
            )
        )
        geom.visual.vertex_attributes["color"] = _shade(geom, rgb)
        touched = True

    if not touched:
        return glb
    return scene.export(file_type="glb")


def _has_real_texture(visual) -> bool:
    """True when a TextureVisuals actually carries an image, not just a material."""
    material = getattr(visual, "material", None)
    image = getattr(material, "image", None) or getattr(material, "baseColorTexture", None)
    return image is not None


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
    """Reconstruct from 2-4 labelled views. Returns raw, untinted .glb bytes.

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

    # Deliberately NOT tinted here. normalize_glb (step 07) rebuilds the
    # material and converts vertex colours to a texture, silently losing them —
    # the building then renders plain grey. The caller tints after normalizing.
    return raw
