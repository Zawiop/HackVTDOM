"""generateRedesignedImage (spec: markdown_files/05-image-edit-gemini.md).

Photo + World State prompt -> redesigned image URL. Providers, in IMAGE_PROVIDERS order:
  gemini  - Gemini API image model. Wired per the spec, but the team key has free-tier
            limit 0 for every image model (see file 05 CAPTURED EXAMPLE), so today it 429s
            instantly and is put on cooldown.
  kontext - FLUX.1 Kontext [dev] HF Space via gradio_client (the working free path).
  hf-inference - the same Kontext model through HF Inference Providers, on the token's monthly
            credits: a separate pool from the Space's daily ZeroGPU quota, so it still answers
            when the Space is exhausted. Last, because that daily pool is the bigger one.
The whole chain shares one IMAGE_TIMEOUT_S budget.
"""
import io
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from . import config, storage
from .providers import ProviderError, ProviderTimeout, cooling_down, looks_like_quota, run_blocking, start_cooldown

# Kontext re-imagines the whole scene when handed a bare scene description (it replaced
# Burruss Hall's tower and wings with a generic house in testing). Stating what to keep
# *before* the World State text makes it edit the building instead of replacing it.
PROMPT_TEMPLATE = (
    "Edit this photo of a real building. Keep the exact same building: the same architecture, "
    "towers, wings, roofline, window layout and proportions, seen from the same camera angle "
    "with the same framing. Change only its condition, materials and surroundings to match "
    "this scene: {prompt}"
)
MAX_INPUT_SIDE = 1536
CACHE_VERSION = "image-v1"


class BadImage(ValueError):
    pass


class ImageGenerationFailed(Exception):
    def __init__(self, message: str, attempts: list[dict], timed_out: bool):
        super().__init__(message)
        self.attempts = attempts
        self.timed_out = timed_out


def prepare_photo(data: bytes) -> bytes:
    """Decode any PIL-readable upload, apply EXIF rotation (phone photos), cap size, re-encode JPEG."""
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img).convert("RGB")
    except (UnidentifiedImageError, OSError) as e:
        raise BadImage(f"could not read image: {e}") from None
    img.thumbnail((MAX_INPUT_SIDE, MAX_INPUT_SIDE))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=92)
    return out.getvalue()


def _gemini(jpeg: bytes, prompt: str, deadline: float) -> bytes:
    from google import genai
    from google.genai import errors, types

    if not config.GEMINI_API_KEY:
        raise ProviderError("gemini", "GEMINI_API_KEY not set")
    remaining_ms = int(max(1.0, deadline - time.monotonic()) * 1000)
    client = genai.Client(api_key=config.GEMINI_API_KEY, http_options=types.HttpOptions(timeout=remaining_ms))
    try:
        response = client.models.generate_content(
            model=config.GEMINI_IMAGE_MODEL,
            contents=[
                types.Part.from_text(text=prompt),
                types.Part.from_bytes(data=jpeg, mime_type="image/jpeg"),
            ],
            config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]),
        )
    except errors.APIError as e:
        full = str(e.message)
        if e.code == 429 and "limit: 0" in full:
            # Captured in file 05: the free tier allots zero image requests to this key.
            msg = f"429 {e.status}: free-tier limit: 0 for {config.GEMINI_IMAGE_MODEL} (no image quota on this key)"
        else:
            msg = f"{e.code} {e.status}: {full[:300]}"
        raise ProviderError("gemini", msg, quota=e.code == 429) from None
    for cand in response.candidates or []:
        for part in (cand.content.parts if cand.content else None) or []:
            if part.inline_data is not None and part.inline_data.data:
                return part.inline_data.data
    text = (response.text or "")[:200] if response.candidates else ""
    raise ProviderError("gemini", f"response had no image part (text: {text!r})")


def _kontext(jpeg: bytes, prompt: str, deadline: float) -> bytes:
    from gradio_client import Client, handle_file

    with tempfile.TemporaryDirectory(dir=config.OUTPUT_DIR) as tmp:
        src = Path(tmp) / "input.jpg"
        src.write_bytes(jpeg)
        try:
            client = Client(config.KONTEXT_SPACE, token=config.HF_TOKEN, verbose=False, download_files=tmp)
            job = client.submit(
                input_image=handle_file(str(src)),
                prompt=prompt,
                seed=0,
                randomize_seed=True,
                guidance_scale=config.KONTEXT_GUIDANCE,
                steps=28,
                api_name="/infer",
            )
            try:
                result = job.result(timeout=max(1.0, deadline - time.monotonic()))
            except TimeoutError:
                job.cancel()
                raise
        except TimeoutError:
            raise
        except Exception as e:  # gradio AppError / ValueError (space down) / network
            msg = str(e)[:300]
            raise ProviderError("kontext", f"{type(e).__name__}: {msg}", quota=looks_like_quota(msg)) from None
        # Captured contract: (result_image, seed); result_image is a local filepath (or filedata dict).
        out = result[0]
        path = out.get("path") if isinstance(out, dict) else out
        if not path or not Path(path).is_file():
            raise ProviderError("kontext", f"unexpected result shape: {result!r:.200}")
        return Path(path).read_bytes()


def _hf_inference(jpeg: bytes, prompt: str, deadline: float) -> bytes:
    """Captured contract (file 05): InferenceClient.image_to_image returns a decoded PIL image."""
    from huggingface_hub import InferenceClient

    if not config.HF_TOKEN:
        raise ProviderError("hf-inference", "HF_TOKEN not set")
    client = InferenceClient(
        provider=config.HF_INFERENCE_PROVIDER,
        api_key=config.HF_TOKEN,
        timeout=max(1.0, deadline - time.monotonic()),
    )
    try:
        image = client.image_to_image(jpeg, prompt=prompt, model=config.HF_INFERENCE_MODEL)
    except Exception as e:
        msg = str(e)[:300]
        raise ProviderError("hf-inference", f"{type(e).__name__}: {msg}", quota=looks_like_quota(msg)) from None
    out = io.BytesIO()
    image.convert("RGB").save(out, "PNG")
    return out.getvalue()


_PROVIDERS = {"gemini": _gemini, "kontext": _kontext, "hf-inference": _hf_inference}


async def generate_redesigned_image(photo: bytes, world_state_prompt: str, *, force: bool = False) -> dict:
    t0 = time.monotonic()
    jpeg = prepare_photo(photo)
    prompt = PROMPT_TEMPLATE.format(prompt=world_state_prompt.strip())
    key = storage.sha256(CACHE_VERSION, jpeg, prompt)
    _, source_url = storage.save_bytes(jpeg, "photos", "jpg")

    if not force and (hit := storage.cache_get(key)):
        return {**hit, "cached": True, "elapsedMs": int((time.monotonic() - t0) * 1000)}

    deadline = t0 + config.IMAGE_TIMEOUT_S
    attempts: list[dict] = []
    timed_out = False
    for name in config.IMAGE_PROVIDERS:
        fn = _PROVIDERS.get(name)
        if fn is None:
            attempts.append({"provider": name, "ok": False, "error": "unknown provider"})
            continue
        if reason := cooling_down(name):
            attempts.append({"provider": name, "ok": False, "skipped": True, "error": reason})
            continue
        remaining = deadline - time.monotonic()
        if remaining < 5:
            timed_out = True
            break
        started = time.monotonic()
        try:
            raw = await run_blocking(lambda d, fn=fn: fn(jpeg, prompt, d), remaining, name)
        except ProviderError as e:
            attempts.append({"provider": name, "ok": False, "error": e.message, "ms": int((time.monotonic() - started) * 1000)})
            if e.quota:
                # "limit: 0" means there is no quota at all -> don't retry for an hour.
                start_cooldown(name, f"quota: {e.message[:120]}", 3600 if "limit: 0" in e.message else config.PROVIDER_COOLDOWN_S)
            timed_out = timed_out or isinstance(e, ProviderTimeout)
            continue
        try:
            img = Image.open(io.BytesIO(raw)).convert("RGB")
        except (UnidentifiedImageError, OSError):
            attempts.append({"provider": name, "ok": False, "error": "provider returned undecodable image"})
            continue
        png = io.BytesIO()
        img.save(png, "PNG")
        _, image_url = storage.save_bytes(png.getvalue(), "images", "png")
        attempts.append({"provider": name, "ok": True, "ms": int((time.monotonic() - started) * 1000)})
        result = {
            "imageUrl": image_url,
            "sourcePhotoUrl": source_url,
            "provider": name,
            "model": {"gemini": config.GEMINI_IMAGE_MODEL, "kontext": config.KONTEXT_SPACE}.get(
                name, config.HF_INFERENCE_MODEL
            ),
            "width": img.width,
            "height": img.height,
            "attempts": attempts,
        }
        storage.cache_put(key, result)
        return {**result, "cached": False, "elapsedMs": int((time.monotonic() - t0) * 1000)}

    raise ImageGenerationFailed("all image providers failed", attempts, timed_out)
