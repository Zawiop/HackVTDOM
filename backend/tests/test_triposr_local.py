"""Local TripoSR through the real route, on a real generated image. Opt in: pytest -m heavy.

Needs the one-time setup in app/generation/triposr_local.py (repo clone + ~1.7 GB weights) and
the rembg cutout model; skips if either is missing. No network or HF quota used.
"""
import io
from pathlib import Path

import pytest
import trimesh
from fastapi.testclient import TestClient

from app.generation import config, providers, storage, triposr_local
from app.main import app

pytestmark = pytest.mark.heavy
SAMPLE = Path(__file__).resolve().parents[1] / "assets" / "samples" / "burruss_flooded.png"

if triposr_local.available():
    pytest.skip(f"local TripoSR unavailable: {triposr_local.available()}", allow_module_level=True)


def test_generate_mesh_route_with_local_triposr(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(storage, "_CACHE_FILE", tmp_path / "cache.json")
    monkeypatch.setattr(providers, "_cooldown_until", {})
    monkeypatch.setattr(config, "MESH_PROVIDERS", ["triposr-local"])
    client = TestClient(app)
    r = client.post(
        "/api/generate-mesh",
        files={"image": ("burruss_flooded.png", SAMPLE.read_bytes(), "image/png")},
        data={"footprintWidthMeters": "101.88", "footprintDepthMeters": "70.79"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provider"] == "triposr-local", body["attempts"]
    assert body["confidence"] == "auto-high"
    path = storage.local_path_for_url(body["meshUrl"])
    mesh = trimesh.load(path, force="scene").to_geometry()
    lo, hi = mesh.bounds
    assert lo[1] == pytest.approx(0, abs=1e-3)
    assert max(mesh.extents[0], mesh.extents[2]) == pytest.approx(101.88, rel=1e-2)
    # Upright: a building photo is wider than it is tall, so height must not be the longest side.
    assert mesh.extents[1] < mesh.extents[0]
    assert isinstance(mesh.visual, trimesh.visual.TextureVisuals)
    assert len(mesh.faces) <= triposr_local.MAX_FACES
