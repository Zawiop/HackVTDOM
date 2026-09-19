"""Live contract tests: real photo -> running server -> real providers -> contract checks.

Start the server first (from backend/: .venv/bin/uvicorn app.main:app --port 8000), then:
  .venv/bin/pytest -m live tests/test_live_routes.py -q -s
API_BASE overrides the server URL. LIVE_FORCE=1 bypasses the result cache so the providers
are really called (each image costs ~30 s of the HF token's daily ZeroGPU quota).
"""
import io
import os
from pathlib import Path

import httpx
import numpy as np
import pytest
import trimesh
from PIL import Image

API = os.environ.get("API_BASE", "http://localhost:8000").rstrip("/")
FORCE = os.environ.get("LIVE_FORCE") == "1"
FIXTURES = Path(__file__).parent / "fixtures"
PHOTO = FIXTURES / "burruss_hall.jpg"
PROMPT = (
    "Flooded: murky green floodwater has risen to the first-floor windowsills, reflecting the "
    "building; waterlines and algae stain the stone, debris floats past, overcast amber-green light."
)
FOOTPRINT = (95.0, 40.0)

pytestmark = pytest.mark.live


def _server_up() -> bool:
    try:
        return httpx.get(f"{API}/api/health", timeout=5).status_code == 200
    except httpx.HTTPError:
        return False


if not _server_up():
    pytest.skip(f"API server not reachable at {API}", allow_module_level=True)

client = httpx.Client(base_url=API, timeout=200)


@pytest.fixture(scope="module")
def image_result():
    r = client.post(
        "/api/generate-image",
        files={"photo": ("burruss_hall.jpg", PHOTO.read_bytes(), "image/jpeg")},
        data={"worldStatePrompt": PROMPT, "force": "true" if FORCE else "false"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    print("\ngenerate-image:", {k: body[k] for k in ("imageUrl", "provider", "cached", "elapsedMs")})
    return body


def fetch(url: str) -> httpx.Response:
    r = httpx.get(url, timeout=30)
    assert r.status_code == 200, f"{url} -> {r.status_code}"
    return r


# ---------------------------------------------------------------- /api/generate-image

def test_image_contract(image_result):
    body = image_result
    for key, typ in {
        "imageUrl": str, "sourcePhotoUrl": str, "provider": str, "model": str, "width": int,
        "height": int, "attempts": list, "cached": bool, "elapsedMs": int,
    }.items():
        assert isinstance(body.get(key), typ), f"{key} missing or not {typ.__name__}"
    assert body["provider"] in ("gemini", "kontext")
    assert body["attempts"][-1]["ok"] is True and body["attempts"][-1]["provider"] == body["provider"]


def test_image_url_serves_a_distinct_png(image_result):
    r = fetch(image_result["imageUrl"])
    assert r.headers["content-type"] == "image/png"
    out = Image.open(io.BytesIO(r.content)).convert("RGB")
    assert out.size == (image_result["width"], image_result["height"])
    src = Image.open(PHOTO).convert("RGB").resize(out.size)
    diff = np.abs(np.asarray(out, float) - np.asarray(src, float)).mean()
    assert diff > 10, f"output barely differs from the source photo (mean abs diff {diff:.1f})"
    assert fetch(image_result["sourcePhotoUrl"]).headers["content-type"] == "image/jpeg"


def test_image_is_cached_on_repeat(image_result):
    r = client.post(
        "/api/generate-image",
        files={"photo": ("burruss_hall.jpg", PHOTO.read_bytes(), "image/jpeg")},
        data={"worldStatePrompt": PROMPT},
    )
    assert r.status_code == 200
    assert r.json()["cached"] is True and r.json()["imageUrl"] == image_result["imageUrl"]


def test_foundation_path_aliases(image_result):
    """The skeleton reserved /generate/image and /generate/mesh; both spellings must work."""
    r = client.post(
        "/api/generate/image",
        files={"photo": ("burruss_hall.jpg", PHOTO.read_bytes(), "image/jpeg")},
        data={"worldStatePrompt": PROMPT},
    )
    assert r.status_code == 200 and r.json()["imageUrl"] == image_result["imageUrl"]
    r = client.post(
        "/api/generate/mesh",
        json={"imageUrl": image_result["imageUrl"], "footprintWidthMeters": FOOTPRINT[0],
              "footprintDepthMeters": FOOTPRINT[1]},
    )
    assert r.status_code == 200, r.text
    check_mesh_contract(r.json())


@pytest.mark.parametrize(
    "files,data,status",
    [
        ({}, {"worldStatePrompt": "x"}, 400),
        ({"photo": ("a.jpg", PHOTO.read_bytes(), "image/jpeg")}, {}, 400),
        ({"photo": ("a.jpg", b"not an image at all", "image/jpeg")}, {"worldStatePrompt": "x"}, 415),
    ],
    ids=["missing-photo", "missing-prompt", "not-an-image"],
)
def test_image_errors(files, data, status):
    r = client.post("/api/generate-image", files=files or None, data=data)
    assert r.status_code == status, r.text
    assert "detail" in r.json()


# ----------------------------------------------------------------- /api/generate-mesh

def check_mesh_contract(body: dict, footprint=FOOTPRINT):
    for key in ("meshUrl", "cutoutUrl", "confidence", "provider", "normalization", "warnings", "attempts", "cached", "elapsedMs"):
        assert key in body, f"missing {key}"
    assert body["confidence"] in ("auto-high", "auto-low")
    if body["provider"] == "placeholder":
        assert body["confidence"] == "auto-low" and body["fallbackReason"]
    else:
        assert body["rawMeshUrl"]
    norm = body["normalization"]
    assert norm["pivot"] == "base-center" and "+Y up" in norm["convention"]

    r = fetch(body["meshUrl"])
    assert r.headers["content-type"] == "model/gltf-binary"
    mesh = trimesh.load(io.BytesIO(r.content), file_type="glb", force="scene").to_geometry()
    lo, hi = mesh.bounds
    assert lo[1] == pytest.approx(0, abs=1e-3), "mesh base must be at y=0 (not floating/sunk)"
    assert (lo[0] + hi[0]) / 2 == pytest.approx(0, abs=1e-3) and (lo[2] + hi[2]) / 2 == pytest.approx(0, abs=1e-3)
    assert max(mesh.extents[0], mesh.extents[2]) == pytest.approx(max(footprint), rel=1e-2)
    assert 2 <= mesh.extents[1] <= 200, "height should be building-sized"
    return mesh


def test_mesh_from_image_url(image_result):
    r = client.post(
        "/api/generate-mesh",
        json={"imageUrl": image_result["imageUrl"], "footprintWidthMeters": FOOTPRINT[0],
              "footprintDepthMeters": FOOTPRINT[1], "force": FORCE},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    print("\ngenerate-mesh:", {k: body[k] for k in ("meshUrl", "provider", "confidence", "cached", "elapsedMs")})
    check_mesh_contract(body)


def test_mesh_from_multipart_upload(image_result):
    img = fetch(image_result["imageUrl"]).content
    r = client.post(
        "/api/generate-mesh",
        files={"image": ("redesign.png", img, "image/png")},
        data={"footprintWidthMeters": "60", "footprintDepthMeters": "25"},
    )
    assert r.status_code == 200, r.text
    check_mesh_contract(r.json(), footprint=(60.0, 25.0))


@pytest.mark.parametrize(
    "kwargs,status",
    [
        ({"json": {}}, 400),
        ({"json": {"imageUrl": "http://localhost:8000/assets/placeholder.glb", "footprintWidthMeters": -3}}, 400),
        ({"files": {"image": ("x.png", b"garbage", "image/png")}}, 415),
    ],
    ids=["no-image", "bad-footprint", "not-an-image"],
)
def test_mesh_errors(kwargs, status):
    r = client.post("/api/generate-mesh", **kwargs)
    assert r.status_code == status, r.text
    assert "detail" in r.json()


def test_mesh_normalize_route_refits_existing_mesh():
    r = client.post(
        "/api/mesh/normalize",
        files={"mesh": ("raw.glb", (FIXTURES / "sf3d_raw.glb").read_bytes(), "model/gltf-binary")},
        data={"source": "sf3d", "footprintWidthMeters": "50", "footprintDepthMeters": "20"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["normalization"]["front"]["yawDegrees"] == 180
    mesh = trimesh.load(io.BytesIO(fetch(body["meshUrl"]).content), file_type="glb", force="scene").to_geometry()
    assert max(mesh.extents[0], mesh.extents[2]) == pytest.approx(50, rel=1e-2)


def test_generate_status_reports_providers():
    body = client.get("/api/generate/status").json()
    assert set(body["spaces"]) >= {"stabilityai/TripoSR", "stabilityai/stable-fast-3d"}
    assert fetch(body["placeholderUrl"]).headers["content-type"] == "model/gltf-binary"
