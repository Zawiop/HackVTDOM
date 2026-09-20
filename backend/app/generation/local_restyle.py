"""Last-resort image restyle that runs here, with no external service.

Every hosted image provider we have is behind a paywall or an exhausted free
tier — Gemini reports `limit: 0` for its image model, the Hugging Face ZeroGPU
Space is out of daily quota, and hf-inference answers 402. That is not
something code can fix, but it must not mean the product stops working: a
judge clicking a building has to get *something* back.

So this is a deterministic local restyle: neutral soot/ash surface weathering
for scorched; a colour grade, haze and vignette for the other states. It is
NOT image generation and nothing here pretends otherwise — the response marks
the provider `local-restyle` and the UI says so. What it buys is a pipeline
that always completes: the photo still becomes a distinct per-state image, the
mesh step still runs on it, and the building still lands on the map.
"""
from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

from .scorch_material import scorch_surface

# (tint rgb, tint strength, brightness, contrast, saturation, haze rgb, haze strength)
_GRADES: dict[str, dict] = {
    "scorched": {
        "tint": (196, 118, 48), "tint_strength": 0.34,
        "brightness": 0.82, "contrast": 1.22, "saturation": 0.72,
        "haze": (188, 132, 68), "haze_strength": 0.22, "vignette": 0.45,
    },
    "flooded": {
        "tint": (42, 104, 116), "tint_strength": 0.38,
        "brightness": 0.78, "contrast": 1.12, "saturation": 0.64,
        "haze": (54, 110, 118), "haze_strength": 0.26, "vignette": 0.4,
    },
    "reclaimed": {
        "tint": (74, 122, 56), "tint_strength": 0.3,
        "brightness": 0.94, "contrast": 1.06, "saturation": 1.1,
        "haze": (120, 150, 92), "haze_strength": 0.18, "vignette": 0.3,
    },
    "buried": {
        "tint": (204, 178, 130), "tint_strength": 0.42,
        "brightness": 1.04, "contrast": 0.92, "saturation": 0.5,
        "haze": (214, 192, 150), "haze_strength": 0.34, "vignette": 0.25,
    },
    "petrified": {
        "tint": (146, 148, 150), "tint_strength": 0.52,
        "brightness": 0.9, "contrast": 1.18, "saturation": 0.18,
        "haze": (150, 152, 156), "haze_strength": 0.22, "vignette": 0.38,
    },
}

_DEFAULT = _GRADES["scorched"]

# Matched against the resolved prompt when no state id is passed through.
_KEYWORDS = {
    "flooded": ("flood", "water", "submerg", "waterlog"),
    "reclaimed": ("moss", "ivy", "overgrow", "vegetat", "forest", "reclaim"),
    "buried": ("sand", "dune", "buried", "silt"),
    "petrified": ("ash", "petrif", "grey", "gray", "calcif"),
    "scorched": ("scorch", "burn", "fire", "char", "ember"),
}


def infer_world_state(prompt: str) -> str:
    """Best guess at the state from a prompt, for callers that do not pass one."""
    low = (prompt or "").lower()
    best, score = "scorched", 0
    for state, words in _KEYWORDS.items():
        hits = sum(1 for w in words if w in low)
        if hits > score:
            best, score = state, hits
    return best


def _vignette(size: tuple[int, int], strength: float) -> np.ndarray:
    w, h = size
    ys, xs = np.mgrid[0:h, 0:w]
    cx, cy = (w - 1) / 2, (h - 1) / 2
    # Normalised distance from centre, 0 in the middle and 1 at the corners.
    d = np.sqrt(((xs - cx) / max(cx, 1)) ** 2 + ((ys - cy) / max(cy, 1)) ** 2)
    return 1.0 - strength * np.clip(d / np.sqrt(2), 0, 1) ** 1.6


def restyle(photo: bytes, world_state: str | None, prompt: str = "") -> bytes:
    """Return a JPEG of the photo graded into `world_state`."""
    state = world_state if world_state in _GRADES else infer_world_state(prompt)
    g = _GRADES.get(state, _DEFAULT)

    img = Image.open(io.BytesIO(photo))
    img = img.convert("RGB")

    if state == "scorched":
        # Surface detail remains in place; no orange wash, haze or silhouette edits.
        out = scorch_surface(img).convert("RGB")
        buf = io.BytesIO()
        out.save(buf, format="JPEG", quality=90)
        return buf.getvalue()

    img = ImageEnhance.Color(img).enhance(g["saturation"])
    img = ImageEnhance.Brightness(img).enhance(g["brightness"])
    img = ImageEnhance.Contrast(img).enhance(g["contrast"])

    arr = np.asarray(img).astype(np.float32) / 255.0

    tint = np.array(g["tint"], dtype=np.float32) / 255.0
    arr = arr * (1 - g["tint_strength"]) + tint * g["tint_strength"]

    # Haze thickens towards the horizon, which is what sells weather and dust.
    h = arr.shape[0]
    depth = np.linspace(0.25, 1.0, h, dtype=np.float32)[:, None, None]
    haze = np.array(g["haze"], dtype=np.float32) / 255.0
    arr = arr * (1 - g["haze_strength"] * depth) + haze * (g["haze_strength"] * depth)

    arr = arr * _vignette((arr.shape[1], arr.shape[0]), g["vignette"])[:, :, None]

    out = Image.fromarray(np.clip(arr * 255.0, 0, 255).astype(np.uint8))
    if state in ("buried", "petrified"):
        out = out.filter(ImageFilter.GaussianBlur(0.6))  # dust softens detail

    buf = io.BytesIO()
    out.save(buf, format="JPEG", quality=90)
    return buf.getvalue()
