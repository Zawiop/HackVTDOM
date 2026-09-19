"""Door detection on a real generated building. Opt in: pytest -m heavy.

Uses the committed scorched Burruss Hall image and the real SF3D mesh generated from it
(tests/fixtures/sf3d_raw.glb), the rembg cutout model and OWLv2 (~600 MB on first use).
"""
import io
from pathlib import Path

import numpy as np
import pytest
import trimesh
from PIL import Image

from app.generation import entrances
from app.generation.mesh_generate import cut_out_building
from app.generation.mesh_normalize import normalize_glb

pytestmark = pytest.mark.heavy
BACKEND = Path(__file__).resolve().parents[1]

if entrances.available():
    pytest.skip(entrances.available(), allow_module_level=True)


def test_burruss_main_entrance_is_found_and_marked():
    image = Image.open(BACKEND / "assets" / "samples" / "burruss_scorched.png").convert("RGB")
    cutout, _ = cut_out_building(image)
    alpha = np.asarray(cutout)[:, :, 3]
    glb, rep = normalize_glb((BACKEND / "tests" / "fixtures" / "sf3d_raw.glb").read_bytes(), "sf3d", 101.88, 70.79)

    marked, ents, warnings = entrances.mark_entrances(glb, "sf3d", rep["transform"], image, alpha)

    assert ents and ents[0]["source"] == "detected", warnings
    main = ents[0]
    assert main["isMain"] and main["score"] >= 0.3
    # Burruss's arched entrance sits under the tower, left of center in the photo (-X here).
    x0, _, x1, _ = main["imageBox"]
    assert 380 < (x0 + x1) / 2 < 520
    assert main["position"][0] < 0
    assert main["facing"][2] > 0.9  # faces out of the facade (+Z)
    ext = rep["extentsMeters"]
    assert 0 <= main["position"][1] < 0.5 * ext["height"]  # low on the building, not a window
    assert main["heightMeters"] < 0.4 * ext["height"]
    scene = trimesh.load(io.BytesIO(marked), file_type="glb", force="scene")
    assert any(name.startswith("entrance_0") for name in scene.geometry)
