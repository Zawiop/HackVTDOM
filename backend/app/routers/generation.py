"""Steps 05-07: /generate-image, /generate-mesh, /mesh/normalize (+ provider status).

Both spellings are served for the two generate routes: `/generate-image` (the build brief)
and `/generate/image` (the path reserved in the foundation skeleton), likewise for mesh.
Errors use FastAPI's `{"detail": ...}` shape so frontend/src/api/client.ts can read them.
"""
import asyncio
import math
import mimetypes
import os
import threading
from contextlib import asynccontextmanager
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import UploadFile

from ..generation import config, storage
from ..generation.image_edit import BadImage, ImageGenerationFailed, generate_redesigned_image
from ..generation.mesh_generate import generate_mesh, warm_cutout_model
from ..generation.mesh_normalize import normalize_glb
from ..generation.providers import cooling_down, hf_space_stage
from ..models.contracts import GenerateImageResult, GenerateMeshResult, NormalizeMeshResult
from ..services import worldstate

router = APIRouter(tags=["generation"])

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
mimetypes.add_type("model/gltf-binary", ".glb")


def setup(app: FastAPI) -> None:
    """Serve generated files + the placeholder, and preload the cutout model at startup."""
    app.mount("/outputs", StaticFiles(directory=config.OUTPUT_DIR), name="outputs")
    app.mount("/assets", StaticFiles(directory=config.PLACEHOLDER_GLB.parent), name="assets")
    if os.environ.get("DEBUG_VIEWER") == "1":
        # tests/viewer/deck_check.html: the spec-07 orientation check, served same-origin.
        app.mount("/debug", StaticFiles(directory=config.BACKEND_DIR / "tests" / "viewer"), name="debug")
    # ~1 GB segmentation model, ~20 s cold: load it in the background so boot stays instant.
    # Wraps the existing lifespan (Starlette 1.x dropped add_event_handler/on_startup).
    inner = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app_):
        threading.Thread(target=warm_cutout_model, daemon=True).start()
        async with inner(app_) as state:
            yield state

    app.router.lifespan_context = lifespan


def _error(status: int, message: str, **extra) -> JSONResponse:
    return JSONResponse({"detail": message, **extra}, status_code=status)


def _truthy(value) -> bool:
    return str(value).lower() in ("1", "true", "yes", "on")


def _positive_or_none(value) -> float | None:
    if value in (None, ""):
        return None
    f = float(value)
    if not math.isfinite(f) or f <= 0:
        raise ValueError("must be a positive number")
    return f


async def _read_upload(upload: UploadFile) -> bytes:
    data = await upload.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError(f"file larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    if not data:
        raise ValueError("file is empty")
    return data


async def _fetch_url(url: str) -> bytes:
    if local := storage.local_path_for_url(url):
        return local.read_bytes()
    if urlparse(url).scheme not in ("http", "https"):
        raise ValueError("URL must be http(s)")
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        r = await client.get(url)
    if r.status_code != 200:
        raise ValueError(f"URL returned HTTP {r.status_code}")
    if len(r.content) > MAX_UPLOAD_BYTES:
        raise ValueError("URL content too large")
    return r.content


async def _body(request: Request) -> dict:
    """JSON, multipart or urlencoded, as one dict (UploadFile values for file parts)."""
    if request.headers.get("content-type", "").startswith("application/json"):
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("JSON body must be an object")
        return body
    return dict((await request.form()).items())


async def _file_or_url(body: dict, file_field: str, url_field: str) -> bytes | None:
    value = body.get(file_field)
    if isinstance(value, UploadFile):
        return await _read_upload(value)
    if body.get(url_field):
        return await _fetch_url(str(body[url_field]))
    return None


@router.get("/generate/status")
async def generation_status():
    """Which providers are usable right now, and the live state of each HF Space."""
    spaces = [config.KONTEXT_SPACE, config.TRIPOSR_SPACE, config.SF3D_SPACE]
    stages = await asyncio.gather(*(asyncio.to_thread(hf_space_stage, s) for s in spaces))
    return {
        "imageProviders": {p: cooling_down(p) or "ready" for p in config.IMAGE_PROVIDERS},
        "meshProviders": {p: cooling_down(p) or "ready" for p in config.MESH_PROVIDERS},
        "spaces": dict(zip(spaces, stages)),
        "placeholderUrl": f"{config.PUBLIC_BASE_URL}/assets/placeholder.glb",
    }


@router.post("/generate-image", response_model=GenerateImageResult)
@router.post("/generate/image", response_model=GenerateImageResult, include_in_schema=False)
async def generate_image(request: Request):
    """Step 05. multipart/form-data: `photo` (file), plus the step 04 selection.

    Send `worldState` (one of the five spectrum ids) for the preset path — its locked
    description is resolved server-side so output stays consistent. `worldStatePrompt` is
    the optional freeform override, which *replaces* the preset for that one generation.

    Fails loud (502, or 504 on timeout) with `retryable: true` and the per-provider attempts,
    so the UI can offer a retry instead of freezing.
    """
    try:
        form = await request.form()
    except Exception:
        return _error(400, "expected multipart/form-data with 'photo' and a World State")
    photo = form.get("photo")
    if not isinstance(photo, UploadFile):
        return _error(400, "missing 'photo' file field")

    try:
        prompt, prompt_source, world_state = worldstate.resolve(
            form.get("worldState"), form.get("worldStatePrompt")
        )
    except (worldstate.UnknownWorldState, worldstate.OverrideTooLong) as e:
        return _error(400, str(e))

    try:
        data = await _read_upload(photo)
        result = await generate_redesigned_image(data, prompt, force=_truthy(form.get("force")))
        return {**result, "worldState": world_state, "promptSource": prompt_source}
    except BadImage as e:
        return _error(415, str(e))
    except ValueError as e:
        return _error(400, str(e))
    except ImageGenerationFailed as e:
        return _error(504 if e.timed_out else 502, f"image generation failed: {e}", retryable=True, attempts=e.attempts)


@router.post("/generate-mesh", response_model=GenerateMeshResult)
@router.post("/generate/mesh", response_model=GenerateMeshResult, include_in_schema=False)
async def generate_mesh_route(request: Request):
    """Steps 06+07. JSON, multipart or urlencoded: `image` (file) or `imageUrl`, plus optional
    `footprintWidthMeters`, `footprintDepthMeters` (from step 02) and `force`.

    Always returns a usable mesh: if generation fails or times out, the placeholder comes
    back with `confidence: "auto-low"` and a `fallbackReason`.
    """
    try:
        body = await _body(request)
    except Exception:
        return _error(400, "could not parse request body")
    try:
        width = _positive_or_none(body.get("footprintWidthMeters"))
        depth = _positive_or_none(body.get("footprintDepthMeters"))
    except (TypeError, ValueError):
        return _error(400, "footprintWidthMeters/footprintDepthMeters must be positive numbers")
    try:
        data = await _file_or_url(body, "image", "imageUrl")
        if data is None:
            return _error(400, "provide an 'image' file or an 'imageUrl'")
        return await generate_mesh(data, width, depth, force=_truthy(body.get("force")))
    except BadImage as e:
        return _error(415, str(e))
    except (ValueError, httpx.HTTPError) as e:
        return _error(400, f"could not load image: {e}")


@router.post("/mesh/normalize", response_model=NormalizeMeshResult)
async def normalize_mesh_route(request: Request):
    """Step 07 on its own: re-fit an existing .glb, e.g. once the real footprint is known.

    `mesh` (file) or `meshUrl`, `source` ("sf3d" | "placeholder" | anything else = glTF
    defaults in meters), optional `footprintWidthMeters` / `footprintDepthMeters`.
    """
    try:
        body = await _body(request)
        width = _positive_or_none(body.get("footprintWidthMeters"))
        depth = _positive_or_none(body.get("footprintDepthMeters"))
        data = await _file_or_url(body, "mesh", "meshUrl")
    except (ValueError, TypeError, httpx.HTTPError) as e:
        return _error(400, str(e))
    except Exception:
        return _error(400, "could not parse request body")
    if data is None:
        return _error(400, "provide a 'mesh' file or a 'meshUrl'")
    source = str(body.get("source") or "unknown")
    try:
        glb, report = await asyncio.to_thread(normalize_glb, data, source, width, depth)
    except Exception as e:
        return _error(415, f"could not read mesh: {e}")
    _, url = storage.save_bytes(glb, "meshes", "glb")
    return {"meshUrl": url, "confidence": report["confidence"], "normalization": report}
