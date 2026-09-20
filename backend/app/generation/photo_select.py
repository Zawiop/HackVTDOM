"""Pick the best photo out of several of the same building.

Both models in the chain take exactly one image: Kontext edits one photo, and
SF3D reconstructs from one view. So uploading several photos cannot become
true multi-view reconstruction — that would need a different model entirely,
and pretending otherwise would be a lie about what the mesh is built from.

What several photos *do* buy is choice. Upload order is arbitrary and the
first file a browser hands over is routinely the worst one — a blurry frame, a
dark one, a thumbnail. Scoring them and sending the sharpest, best-exposed,
highest-detail frame is a real quality gain for free, and it is the honest
version of "more photos make a better building".

Scores are returned alongside the result so the UI can say which photo was
used and why, and let the user override the choice.
"""
from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageOps

# A photo below this many pixels carries too little detail to reconstruct from.
_MIN_USEFUL_PIXELS = 160 * 160


def _laplacian_variance(gray: np.ndarray) -> float:
    """Classic blur metric: how much high-frequency detail survives.

    A sharp facade has strong edges at window frames and mortar lines; a
    motion-blurred or out-of-focus frame does not, and SF3D turns that into a
    smooth blob.
    """
    # 3x3 Laplacian, done with slicing so we do not pull in a convolution dep.
    c = gray[1:-1, 1:-1]
    lap = (
        gray[:-2, 1:-1] + gray[2:, 1:-1] + gray[1:-1, :-2] + gray[1:-1, 2:] - 4 * c
    )
    return float(lap.var())


def _exposure_penalty(gray: np.ndarray) -> float:
    """0 when well exposed, approaching 1 when blown out or crushed.

    Clipped highlights and blocked shadows both destroy the geometry cues the
    mesh model reads, and neither is recoverable downstream.
    """
    clipped = float(((gray < 8) | (gray > 247)).mean())
    mean = float(gray.mean()) / 255.0
    drift = abs(mean - 0.46) / 0.46  # how far off a healthy mid-tone
    return min(1.0, clipped * 1.6 + max(0.0, drift - 0.35))


def score_photo(data: bytes) -> dict:
    """Score one photo. Higher `score` is better; 0 means unusable."""
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)  # honour camera rotation
        img = img.convert("L")
    except Exception as e:
        return {"ok": False, "score": 0.0, "error": f"unreadable: {type(e).__name__}", **_blank()}

    w, h = img.size
    pixels = w * h
    if pixels < _MIN_USEFUL_PIXELS:
        return {
            "ok": False, "score": 0.0, "error": "too small to reconstruct from",
            "width": w, "height": h, "sharpness": 0.0, "exposure": 0.0, "detail": 0.0,
        }

    # Work at a fixed size so scores compare across resolutions.
    work = np.asarray(img.resize((320, 320), Image.BILINEAR), dtype=np.float32)

    sharpness = _laplacian_variance(work)
    # Squash into 0..1; ~500 variance is already a crisp photo.
    sharp_n = float(min(1.0, sharpness / 500.0))
    exposure_n = 1.0 - _exposure_penalty(work)
    # Resolution helps, with strongly diminishing returns past ~2MP.
    res_n = float(min(1.0, (pixels / 2_000_000.0) ** 0.5))

    score = 0.55 * sharp_n + 0.25 * exposure_n + 0.20 * res_n
    return {
        "ok": True,
        "score": round(score, 4),
        "sharpness": round(sharp_n, 4),
        "exposure": round(exposure_n, 4),
        "detail": round(res_n, 4),
        "width": w,
        "height": h,
        "error": None,
    }


def _blank() -> dict:
    return {"sharpness": 0.0, "exposure": 0.0, "detail": 0.0, "width": 0, "height": 0}


def choose_best(photos: list[bytes]) -> tuple[int, list[dict]]:
    """Return (index of the best photo, a score per photo in upload order).

    Falls back to the first photo when every candidate scores zero, so a caller
    always gets something to send rather than an error.
    """
    if not photos:
        raise ValueError("no photos given")
    scores = [score_photo(p) for p in photos]
    best = max(range(len(scores)), key=lambda i: scores[i]["score"])
    if scores[best]["score"] <= 0:
        best = 0
    for i, s in enumerate(scores):
        s["chosen"] = i == best
    return best, scores
