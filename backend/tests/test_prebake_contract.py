"""The --live pre-bake path calls providers that quota keeps us from running.

These check the call signatures statically, because the live path is wrapped in
exception handling that turns any mistake into "the provider failed" — which is
exactly how a wrong keyword argument hid as a provider outage.
"""

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.generation.image_edit import generate_redesigned_image  # noqa: E402
from app.generation.mesh_generate import generate_mesh  # noqa: E402
from seed import prebake_demo  # noqa: E402


def test_generate_mesh_accepts_the_arguments_prebake_passes():
    params = inspect.signature(generate_mesh).parameters
    for name in ("footprint_width_m", "footprint_depth_m"):
        assert name in params, f"prebake_demo.generate_live passes {name}"


def test_generate_image_accepts_the_arguments_prebake_passes():
    params = list(inspect.signature(generate_redesigned_image).parameters)
    # prebake calls it positionally: (photo_bytes, prompt).
    assert params[:2] == ["photo", "world_state_prompt"]


def test_live_path_does_not_swallow_programming_errors():
    """A bare `except Exception` would disguise a TypeError as a provider outage."""
    source = inspect.getsource(prebake_demo.generate_live)
    assert "except Exception" not in source


def test_every_demo_entry_has_its_captured_artifacts():
    for entry in prebake_demo.DEMOS:
        for key in ("image", "mesh", "mesh_response"):
            assert entry[key].exists(), f"{entry['world_state']}: missing {key} at {entry[key]}"
    assert prebake_demo.SOURCE_PHOTO.exists()
