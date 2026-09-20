"""The fallback that keeps the product working when every provider is out.

This is a colour grade, not generation, and the tests say so: what matters is
that it always returns a usable image, that the five states are visibly
different from each other and from the source, and that it never raises —
because the whole point is being the thing that cannot fail.
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from app.generation.local_restyle import infer_world_state, restyle

PHOTO = Path(__file__).parent / "fixtures" / "burruss_hall.jpg"
STATES = ["scorched", "flooded", "reclaimed", "buried", "petrified"]


@pytest.fixture(scope="module")
def photo() -> bytes:
    return PHOTO.read_bytes()


def mean_rgb(data: bytes) -> tuple[float, float, float]:
    img = Image.open(io.BytesIO(data)).convert("RGB").resize((32, 32))
    px = list(img.getdata())
    n = len(px)
    return (
        sum(p[0] for p in px) / n,
        sum(p[1] for p in px) / n,
        sum(p[2] for p in px) / n,
    )


@pytest.mark.parametrize("state", STATES)
def test_every_state_returns_a_readable_image(photo, state):
    out = restyle(photo, state)
    img = Image.open(io.BytesIO(out))
    img.verify()
    assert img.format == "JPEG"


def test_states_are_visibly_different_from_each_other(photo):
    # If two states graded the same, the World State would be invisible.
    means = {s: mean_rgb(restyle(photo, s)) for s in STATES}
    for a in STATES:
        for b in STATES:
            if a >= b:
                continue
            spread = max(abs(x - y) for x, y in zip(means[a], means[b]))
            assert spread > 4, f"{a} and {b} grade almost identically"


def test_the_grade_actually_changes_the_photo(photo):
    before = mean_rgb(photo)
    after = mean_rgb(restyle(photo, "flooded"))
    assert max(abs(x - y) for x, y in zip(before, after)) > 10


def test_flooded_is_cooler_than_scorched(photo):
    flooded_r, _, flooded_b = mean_rgb(restyle(photo, "flooded"))
    scorched_r, _, scorched_b = mean_rgb(restyle(photo, "scorched"))
    # Compare colour balance, not absolute brightness. Neutral scorched masonry
    # should not be forced darker/oranger just to match the old global grade.
    assert flooded_b-flooded_r > scorched_b-scorched_r


def test_petrified_is_close_to_grey(photo):
    r, g, b = mean_rgb(restyle(photo, "petrified"))
    assert max(r, g, b) - min(r, g, b) < 14


def test_is_deterministic(photo):
    assert restyle(photo, "buried") == restyle(photo, "buried")


def test_unknown_state_still_produces_an_image(photo):
    out = restyle(photo, "not-a-state")
    Image.open(io.BytesIO(out)).verify()


def test_state_is_inferred_from_the_prompt_when_not_passed():
    assert infer_world_state("standing water never receded, submerged") == "flooded"
    assert infer_world_state("moss and ivy overgrow everything") == "reclaimed"
    assert infer_world_state("sand dunes buried the lower storeys") == "buried"
    assert infer_world_state("turned to ash, calcified") == "petrified"
    assert infer_world_state("fire burnt through, charred") == "scorched"


def test_inference_falls_back_rather_than_failing():
    assert infer_world_state("") in ("scorched",)
    assert infer_world_state("nothing relevant here") in ("scorched",)


def test_greyscale_and_rgba_sources_are_handled(photo):
    src = Image.open(io.BytesIO(photo))
    for mode in ("L", "RGBA", "P"):
        buf = io.BytesIO()
        src.convert(mode).save(buf, format="PNG")
        out = restyle(buf.getvalue(), "reclaimed")
        Image.open(io.BytesIO(out)).verify()
