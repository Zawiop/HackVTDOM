"""Runtime configuration, read once from backend/.env (never committed)."""
import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[2]  # backend/
load_dotenv(BACKEND_DIR / ".env")

# Keep every model/cache download inside the project folder.
CACHE_DIR = BACKEND_DIR / ".cache"
os.environ.setdefault("U2NET_HOME", str(CACHE_DIR / "u2net"))
os.environ.setdefault("NUMBA_CACHE_DIR", str(CACHE_DIR / "numba"))
os.environ.setdefault("MPLCONFIGDIR", str(CACHE_DIR / "mpl"))
# huggingface_hub (gradio_client, TripoSR weights) reads this at import time.
os.environ.setdefault("HF_HOME", str(CACHE_DIR / "hf"))


def _float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


def _list(name: str, default: str) -> list[str]:
    return [p.strip() for p in os.environ.get(name, default).split(",") if p.strip()]


# `or None`: a key left blank in .env means "not set". An empty HF token otherwise goes out as
# an invalid "Authorization: Bearer " header and every Space call fails instead of going anonymous.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or None
HF_TOKEN = os.environ.get("HF_TOKEN") or None

PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", BACKEND_DIR / "outputs"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
PLACEHOLDER_GLB = BACKEND_DIR / "assets" / "placeholder.glb"

# Image edit (file 05). Providers are tried in order until one returns an image.
IMAGE_PROVIDERS = _list("IMAGE_PROVIDERS", "gemini,kontext,hf-inference,local-restyle")
GEMINI_IMAGE_MODEL = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
KONTEXT_SPACE = os.environ.get("KONTEXT_SPACE", "black-forest-labs/FLUX.1-Kontext-Dev")
KONTEXT_GUIDANCE = _float("KONTEXT_GUIDANCE", 2.5)
# Third path: the same Kontext model through HF Inference Providers (the token's monthly credits,
# a separate pool from the Space's daily ZeroGPU quota). Needs the token's "Inference Providers"
# permission. Last in the chain: the Space's free pool is bigger.
HF_INFERENCE_MODEL = os.environ.get("HF_INFERENCE_MODEL", "black-forest-labs/FLUX.1-Kontext-dev")
HF_INFERENCE_PROVIDER = os.environ.get("HF_INFERENCE_PROVIDER", "auto")
IMAGE_TIMEOUT_S = _float("IMAGE_TIMEOUT_S", 60)
# After a quota/429 failure, skip that provider for this long instead of paying for it every request.
PROVIDER_COOLDOWN_S = _float("PROVIDER_COOLDOWN_S", 600)

# Mesh generation (file 06).
MESH_PROVIDERS = _list("MESH_PROVIDERS", "triposr,sf3d,triposr-local")
TRIPOSR_SPACE = os.environ.get("TRIPOSR_SPACE", "stabilityai/TripoSR")
SF3D_SPACE = os.environ.get("SF3D_SPACE", "stabilityai/stable-fast-3d")
MESH_ATTEMPT_TIMEOUT_S = _float("MESH_ATTEMPT_TIMEOUT_S", 75)
MESH_RETRIES = int(os.environ.get("MESH_RETRIES", 1))
CUTOUT_MODEL = os.environ.get("CUTOUT_MODEL", "birefnet-general")

# Mesh normalization (file 07). Used only when the caller has no footprint yet.
DEFAULT_FOOTPRINT_M = _float("DEFAULT_FOOTPRINT_M", 20)
