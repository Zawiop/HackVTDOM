"""Failure handling for both generators (specs 05/06), with the providers stubbed out.

Offline and fast: checks timeouts, retry-once, cooldowns, placeholder fallback and caching
without spending any HF/Gemini quota. Run from backend/: .venv/bin/pytest tests/test_fallbacks.py -q
"""
import asyncio
import io
import time
from pathlib import Path

import pytest
import trimesh
from PIL import Image

from app.generation import config, entrances, image_edit, mesh_generate, providers, storage
from app.generation.providers import ProviderError

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Fresh output dir, cache and cooldown state for every test."""
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(storage, "_CACHE_FILE", tmp_path / "cache.json")
    monkeypatch.setattr(providers, "_cooldown_until", {})
    monkeypatch.setattr(providers, "_cooldown_reason", {})
    monkeypatch.setattr(config, "MESH_ATTEMPT_TIMEOUT_S", 0.5)
    monkeypatch.setattr(config, "MESH_RETRIES", 1)
    # Keep these fast: no door-detector model; every mesh gets the default entrance instead.
    monkeypatch.setattr(entrances, "available", lambda: "detector disabled in tests")


def transparent_png() -> bytes:
    """RGBA input with a transparent background, so the (1 GB) cutout model is skipped."""
    img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    img.paste((150, 120, 90, 255), (60, 40, 200, 230))
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def served_mesh(url: str) -> trimesh.Trimesh:
    path = storage.local_path_for_url(url)
    assert path is not None and path.is_file(), f"{url} is not a file this server serves"
    return trimesh.load(path, force="scene").to_geometry()


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------- mesh (spec 06)

def test_all_providers_fail_falls_back_to_placeholder(monkeypatch):
    def broken(path, deadline):
        raise ProviderError("sf3d", "AppError: boom")

    monkeypatch.setattr(mesh_generate, "_PROVIDERS", {"sf3d": broken})
    monkeypatch.setattr(config, "MESH_PROVIDERS", ["sf3d"])
    res = run(mesh_generate.generate_mesh(transparent_png(), 30.0, 12.0))

    assert res["provider"] == "placeholder"
    assert res["confidence"] == "auto-low"
    assert res["fallbackReason"]
    assert [a["round"] for a in res["attempts"]] == [0, 1]  # tried, then retried once
    mesh = served_mesh(res["meshUrl"])
    assert mesh.bounds[0][1] == pytest.approx(0, abs=1e-4)
    assert max(mesh.extents[0], mesh.extents[2]) == pytest.approx(30.0, rel=5e-3)  # sized to footprint
    # Even the placeholder gets an entrance, marked on the mesh.
    assert len(res["entrances"]) == 1 and res["entrances"][0]["source"] == "default"
    assert res["entrances"][0]["isMain"] is True
    # Failures are not cached: the next request tries the real providers again.
    assert not (config.OUTPUT_DIR / "cache.json").exists()


def test_polite_hang_times_out_then_retries(monkeypatch):
    def hangs(path, deadline):
        while time.monotonic() < deadline:
            time.sleep(0.02)
        raise TimeoutError

    monkeypatch.setattr(mesh_generate, "_PROVIDERS", {"sf3d": hangs})
    monkeypatch.setattr(config, "MESH_PROVIDERS", ["sf3d"])
    t0 = time.monotonic()
    res = run(mesh_generate.generate_mesh(transparent_png(), 30.0, 12.0))
    assert time.monotonic() - t0 < 6
    assert res["provider"] == "placeholder" and res["confidence"] == "auto-low"
    assert all(a["timeout"] for a in res["attempts"]) and len(res["attempts"]) == 2


def test_rude_hang_is_still_cut_off(monkeypatch):
    def ignores_deadline(path, deadline):
        time.sleep(8)
        return b""

    monkeypatch.setattr(mesh_generate, "_PROVIDERS", {"sf3d": ignores_deadline})
    monkeypatch.setattr(config, "MESH_PROVIDERS", ["sf3d"])
    monkeypatch.setattr(config, "MESH_RETRIES", 0)

    async def timed():
        t0 = time.monotonic()
        res = await mesh_generate.generate_mesh(transparent_png(), 30.0, 12.0)
        return res, time.monotonic() - t0

    # Timed inside the loop: asyncio.run()'s teardown waits for the abandoned thread, but a
    # long-running server doesn't, so the response itself is what must be on time.
    res, elapsed = run(timed())
    assert elapsed < 5  # 0.5 s timeout + 2 s backstop grace
    assert res["attempts"][0]["timeout"] is True
    assert res["provider"] == "placeholder"


def test_retry_succeeds_on_second_round(monkeypatch):
    calls = []

    def flaky(path, deadline):
        calls.append(path)
        if len(calls) == 1:
            raise ProviderError("sf3d", "AppError: queue full")
        return (FIXTURES / "sf3d_raw.glb").read_bytes()

    monkeypatch.setattr(mesh_generate, "_PROVIDERS", {"sf3d": flaky})
    monkeypatch.setattr(config, "MESH_PROVIDERS", ["sf3d"])
    res = run(mesh_generate.generate_mesh(transparent_png(), 95.0, 40.0))

    assert res["provider"] == "sf3d" and res["confidence"] == "auto-high"
    assert [(a["round"], a["ok"]) for a in res["attempts"]] == [(0, False), (1, True)]
    assert res["rawMeshUrl"] and served_mesh(res["rawMeshUrl"])
    assert res["normalization"]["front"]["yawDegrees"] == 180
    assert res["entrances"] and "detector disabled in tests" in " ".join(res["warnings"])

    # Success is cached; an identical request comes straight back.
    again = run(mesh_generate.generate_mesh(transparent_png(), 95.0, 40.0))
    assert again["cached"] is True and again["meshUrl"] == res["meshUrl"] and len(calls) == 2


def test_down_provider_falls_through_to_next(monkeypatch):
    def down(path, deadline):
        raise ProviderError("triposr", "Space stabilityai/TripoSR is RUNTIME_ERROR")

    monkeypatch.setattr(
        mesh_generate, "_PROVIDERS",
        {"triposr": down, "sf3d": lambda p, d: (FIXTURES / "sf3d_raw.glb").read_bytes()},
    )
    monkeypatch.setattr(config, "MESH_PROVIDERS", ["triposr", "sf3d"])
    res = run(mesh_generate.generate_mesh(transparent_png(), 95.0, 40.0))
    assert res["provider"] == "sf3d"
    assert res["attempts"][0]["provider"] == "triposr" and not res["attempts"][0]["ok"]


def test_quota_error_puts_provider_on_cooldown(monkeypatch):
    calls = []

    def over_quota(path, deadline):
        calls.append(1)
        raise ProviderError("sf3d", "You have exceeded your GPU quota", quota=True)

    monkeypatch.setattr(mesh_generate, "_PROVIDERS", {"sf3d": over_quota})
    monkeypatch.setattr(config, "MESH_PROVIDERS", ["sf3d"])
    res = run(mesh_generate.generate_mesh(transparent_png(), 30.0, 12.0))
    assert len(calls) == 1  # the retry round skipped it instead of burning another call
    assert res["attempts"][1]["skipped"] is True
    assert providers.cooling_down("sf3d")


def test_corrupt_provider_output_falls_back(monkeypatch):
    monkeypatch.setattr(mesh_generate, "_PROVIDERS", {"sf3d": lambda p, d: b"not a glb"})
    monkeypatch.setattr(config, "MESH_PROVIDERS", ["sf3d"])
    res = run(mesh_generate.generate_mesh(transparent_png(), 30.0, 12.0))
    assert res["provider"] == "placeholder" and res["confidence"] == "auto-low"
    assert "normalization failed" in res["fallbackReason"]


def test_unreadable_image_is_rejected():
    with pytest.raises(image_edit.BadImage):
        run(mesh_generate.generate_mesh(b"definitely not an image"))


# --------------------------------------------------------------- image (spec 05)

def webp_bytes() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (64, 48), (120, 90, 40)).save(out, "WEBP")
    return out.getvalue()


def test_gemini_quota_zero_falls_through_to_kontext(monkeypatch):
    seen = {}

    def gemini(jpeg, prompt, deadline):
        raise ProviderError("gemini", "429 RESOURCE_EXHAUSTED: free-tier limit: 0 for x", quota=True)

    def kontext(jpeg, prompt, deadline):
        seen["prompt"] = prompt
        return webp_bytes()

    monkeypatch.setattr(image_edit, "_PROVIDERS", {"gemini": gemini, "kontext": kontext})
    monkeypatch.setattr(config, "IMAGE_PROVIDERS", ["gemini", "kontext"])
    photo = (FIXTURES / "burruss_hall.jpg").read_bytes()
    res = run(image_edit.generate_redesigned_image(photo, "Flooded to the second floor."))

    assert res["provider"] == "kontext"
    assert storage.local_path_for_url(res["imageUrl"]).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"  # re-encoded
    assert storage.local_path_for_url(res["sourcePhotoUrl"]).is_file()
    assert "Flooded to the second floor." in seen["prompt"] and "Keep the exact same building" in seen["prompt"]
    assert providers.cooling_down("gemini")  # limit: 0 -> skip Gemini on the next request

    again = run(image_edit.generate_redesigned_image(photo, "Flooded to the second floor."))
    assert again["cached"] is True and again["imageUrl"] == res["imageUrl"]


def test_chain_falls_through_to_hf_inference_when_both_are_out_of_quota(monkeypatch):
    """Gemini has no image quota and the Space's daily ZeroGPU pool runs out; credits still answer."""
    calls = []

    def out_of_quota(name, message):
        def fn(jpeg, prompt, deadline):
            calls.append(name)
            raise ProviderError(name, message, quota=True)

        return fn

    monkeypatch.setattr(image_edit, "_PROVIDERS", {
        "gemini": out_of_quota("gemini", "429 RESOURCE_EXHAUSTED: free-tier limit: 0 for x"),
        "kontext": out_of_quota("kontext", "AppError: You have exceeded your ZeroGPU runs limit."),
        "hf-inference": lambda jpeg, prompt, deadline: (calls.append("hf-inference"), webp_bytes())[1],
    })
    monkeypatch.setattr(config, "IMAGE_PROVIDERS", ["gemini", "kontext", "hf-inference"])
    res = run(image_edit.generate_redesigned_image((FIXTURES / "burruss_hall.jpg").read_bytes(), "Petrified in ash."))

    assert calls == ["gemini", "kontext", "hf-inference"]
    assert res["provider"] == "hf-inference" and res["model"] == config.HF_INFERENCE_MODEL
    assert [a["ok"] for a in res["attempts"]] == [False, False, True]
    assert providers.cooling_down("kontext")  # don't re-ask the Space until the quota resets


def test_image_timeout_fails_loud(monkeypatch):
    def hangs(jpeg, prompt, deadline):
        while time.monotonic() < deadline:
            time.sleep(0.02)
        raise TimeoutError

    monkeypatch.setattr(image_edit, "_PROVIDERS", {"kontext": hangs})
    monkeypatch.setattr(config, "IMAGE_PROVIDERS", ["kontext"])
    monkeypatch.setattr(config, "IMAGE_TIMEOUT_S", 6)
    t0 = time.monotonic()
    with pytest.raises(image_edit.ImageGenerationFailed) as e:
        run(image_edit.generate_redesigned_image((FIXTURES / "burruss_hall.jpg").read_bytes(), "Buried in sand."))
    assert time.monotonic() - t0 < 10
    assert e.value.timed_out is True


def test_exif_rotation_is_applied():
    img = Image.new("RGB", (400, 200), (10, 20, 30))
    exif = img.getexif()
    exif[0x0112] = 6  # "rotate 90 CW to display" as phones write it
    out = io.BytesIO()
    img.save(out, "JPEG", exif=exif.tobytes())
    prepared = Image.open(io.BytesIO(image_edit.prepare_photo(out.getvalue())))
    assert prepared.size == (200, 400)
