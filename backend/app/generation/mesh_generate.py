"""generateMesh (spec: markdown_files/06-mesh-generate-triposr.md) + normalizeMesh (07).

Image -> raw .glb -> normalized .glb URL. Providers, in MESH_PROVIDERS order:
  triposr - stabilityai/TripoSR Space. Currently RUNTIME_ERROR (see file 06 CAPTURED
            EXAMPLE); we check its runtime stage (cached) and skip it while it's down.
  sf3d    - stabilityai/stable-fast-3d Space, called with the captured working sequence.
  triposr-local - the TripoSR model run on this machine (app/generation/triposr_local.py):
            no queue, no quota. Last resort before the placeholder.
Each attempt gets MESH_ATTEMPT_TIMEOUT_S, and the chain is retried MESH_RETRIES times.
If everything fails, the committed placeholder .glb is returned with confidence "auto-low"
(the team-wide vocabulary from files 08/09/11; file 06 says "low").
"""
import asyncio
import io
import tempfile
import threading
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from . import config, storage
from .image_edit import BadImage
from .mesh_normalize import normalize_glb
from .providers import (
    ProviderError,
    ProviderTimeout,
    cooling_down,
    hf_space_stage,
    looks_like_quota,
    run_blocking,
    start_cooldown,
)

CACHE_VERSION = "mesh-v4"  # bump whenever normalization output changes
MIN_FOREGROUND_FRACTION = 0.02

_cutout_session = None
_cutout_lock = threading.Lock()


def _get_cutout_session():
    global _cutout_session
    with _cutout_lock:
        if _cutout_session is None:
            from rembg import new_session

            _cutout_session = new_session(config.CUTOUT_MODEL)
        return _cutout_session


def warm_cutout_model() -> None:
    """Load the segmentation model (~1 GB, ~20 s cold) so the first request doesn't pay for it."""
    _get_cutout_session()


def cut_out_building(image: Image.Image) -> tuple[Image.Image, float]:
    """Return an RGBA image with the background transparent, plus the foreground fraction."""
    from rembg import remove

    rgba = remove(image.convert("RGB"), session=_get_cutout_session())
    alpha = np.asarray(rgba)[:, :, 3]
    return rgba, float((alpha > 128).mean())


def _triposr(image_path: Path, deadline: float) -> bytes:
    stage = hf_space_stage(config.TRIPOSR_SPACE)
    if stage != "RUNNING":
        start_cooldown("triposr", f"Space {config.TRIPOSR_SPACE} is {stage}", 300)
        raise ProviderError("triposr", f"Space {config.TRIPOSR_SPACE} is {stage}")
    # It came back up. Its API was never captured while it was working (file 06), so we
    # refuse to call a guessed signature; re-run scripts/capture_hf.py and wire it here.
    raise ProviderError("triposr", "Space is RUNNING again but its API contract is uncaptured; skipping")


def _sf3d(image_path: Path, deadline: float) -> bytes:
    """Captured working sequence (file 06): seed session state, then run with explicit inputs."""
    from gradio_client import Client, handle_file

    with tempfile.TemporaryDirectory(dir=config.OUTPUT_DIR) as tmp:
        try:
            # One Client per attempt = one Gradio session, so concurrent requests can't share state.
            client = Client(
                config.SF3D_SPACE, token=config.HF_TOKEN, verbose=False, download_files=tmp, _skip_components=False
            )
            img = handle_file(str(image_path))
            job = client.submit(img, 0.85, api_name="/requires_bg_remove")
            job.result(timeout=max(1.0, deadline - time.monotonic()))
            job = client.submit("Run", img, None, 0.85, "None", -1, 1024, api_name="/run_button")
            try:
                result = job.result(timeout=max(1.0, deadline - time.monotonic()))
            except TimeoutError:
                job.cancel()
                raise
        except TimeoutError:
            raise
        except Exception as e:  # AppError (incl. ZeroGPU quota), space down, network
            msg = str(e)[:300]
            raise ProviderError("sf3d", f"{type(e).__name__}: {msg}", quota=looks_like_quota(msg)) from None
        # result[4] is the LitModel3D update: {'visible': True, 'value': '<path>.glb', ...}
        model = result[4] if len(result) > 4 else None
        path = model.get("value") if isinstance(model, dict) else model
        if isinstance(path, dict):
            path = path.get("path")
        if not path or not Path(path).is_file():
            raise ProviderError("sf3d", f"no mesh in result: {result!r:.300}")
        return Path(path).read_bytes()


def _triposr_local(image_path: Path, deadline: float) -> bytes:
    """Same TripoSR model, run on this machine: no public queue, no quota (~5 s on Apple MPS)."""
    from . import triposr_local

    if reason := triposr_local.available():
        start_cooldown("triposr-local", reason, 3600)
        raise ProviderError("triposr-local", reason)
    try:
        return triposr_local.generate_glb(Image.open(image_path))
    except Exception as e:
        raise ProviderError("triposr-local", f"{type(e).__name__}: {str(e)[:300]}") from None


_PROVIDERS = {"triposr": _triposr, "sf3d": _sf3d, "triposr-local": _triposr_local}


async def _run_chain(image_path: Path, attempts: list[dict]) -> tuple[bytes, str] | None:
    for round_ in range(1 + config.MESH_RETRIES):
        for name in config.MESH_PROVIDERS:
            fn = _PROVIDERS.get(name)
            if fn is None:
                attempts.append({"provider": name, "round": round_, "ok": False, "error": "unknown provider"})
                continue
            if reason := cooling_down(name):
                attempts.append({"provider": name, "round": round_, "ok": False, "skipped": True, "error": reason})
                continue
            started = time.monotonic()
            try:
                raw = await run_blocking(
                    lambda d, fn=fn: fn(image_path, d), config.MESH_ATTEMPT_TIMEOUT_S, name
                )
            except ProviderError as e:
                attempts.append({
                    "provider": name, "round": round_, "ok": False, "error": e.message,
                    "timeout": isinstance(e, ProviderTimeout), "ms": int((time.monotonic() - started) * 1000),
                })
                if e.quota:
                    start_cooldown(name, f"quota: {e.message[:120]}")
                continue
            attempts.append({"provider": name, "round": round_, "ok": True, "ms": int((time.monotonic() - started) * 1000)})
            return raw, name
        if round_ < config.MESH_RETRIES:
            await asyncio.sleep(2)
    return None


async def generate_mesh(
    image_bytes: bytes,
    footprint_width_m: float | None = None,
    footprint_depth_m: float | None = None,
    *,
    force: bool = False,
) -> dict:
    t0 = time.monotonic()
    try:
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(image_bytes)))
        image.load()
    except OSError as e:
        raise BadImage(f"could not read image: {e}") from None

    fp_key = f"{footprint_width_m}x{footprint_depth_m}"
    key = storage.sha256(CACHE_VERSION, image_bytes, fp_key)
    if not force and (hit := storage.cache_get(key)):
        return {**hit, "cached": True, "elapsedMs": int((time.monotonic() - t0) * 1000)}

    warnings: list[str] = []
    attempts: list[dict] = []

    # Image-to-3D models want an isolated object: cut the building out of the street photo,
    # unless the caller already sent a transparent cutout.
    has_alpha = image.mode in ("RGBA", "LA") and np.asarray(image.convert("RGBA"))[:, :, 3].min() == 0
    if has_alpha:
        rgba, fg = image.convert("RGBA"), None
    else:
        rgba, fg = await asyncio.to_thread(cut_out_building, image)
        if fg < MIN_FOREGROUND_FRACTION:
            warnings.append(f"background removal kept only {fg:.1%} of the image; mesh may be a fragment")
    cut_png = io.BytesIO()
    rgba.save(cut_png, "PNG")
    _, cutout_url = storage.save_bytes(cut_png.getvalue(), "cutouts", "png")

    with tempfile.TemporaryDirectory(dir=config.OUTPUT_DIR) as tmp:
        cut_path = Path(tmp) / "cutout.png"
        cut_path.write_bytes(cut_png.getvalue())
        generated = await _run_chain(cut_path, attempts)

    low = False
    fallback_reason = None
    raw_url = None
    if generated is not None:
        raw, provider = generated
        _, raw_url = storage.save_bytes(raw, "meshes/raw", "glb")
        try:
            glb, norm = await asyncio.to_thread(normalize_glb, raw, provider, footprint_width_m, footprint_depth_m)
        except Exception as e:  # corrupt/empty mesh from the provider -> treat like a failed generation
            generated = None
            fallback_reason = f"normalization failed on {provider} output: {e}"
    else:
        fallback_reason = "all mesh providers failed or timed out"

    if generated is None:
        provider = "placeholder"
        low = True
        warnings.append(f"using placeholder mesh: {fallback_reason}")
        glb, norm = await asyncio.to_thread(
            normalize_glb, config.PLACEHOLDER_GLB.read_bytes(), "placeholder", footprint_width_m, footprint_depth_m
        )

    low = low or norm["confidence"] == "auto-low"
    _, mesh_url = storage.save_bytes(glb, "meshes", "glb")
    result = {
        "meshUrl": mesh_url,
        "rawMeshUrl": raw_url,
        "cutoutUrl": cutout_url,
        "confidence": "auto-low" if low else "auto-high",
        "provider": provider,
        "fallbackReason": fallback_reason,
        "normalization": norm,
        "warnings": warnings + norm["warnings"],
        "attempts": attempts,
    }
    if provider != "placeholder":
        storage.cache_put(key, result)  # only cache real generations; retry failures next time
    return {**result, "cached": False, "elapsedMs": int((time.monotonic() - t0) * 1000)}
