"""Choosing between several photos of the same building.

The models take one image each, so this is selection, not fusion. What matters
is that the worst photo never wins just because the browser handed it over
first, and that nothing here can throw on a caller's bad input.
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image, ImageFilter

from app.generation.photo_select import choose_best, score_photo

PHOTO = Path(__file__).parent / "fixtures" / "burruss_hall.jpg"


@pytest.fixture(scope="module")
def sharp() -> bytes:
    return PHOTO.read_bytes()


def variant(data: bytes, fn) -> bytes:
    img = fn(Image.open(io.BytesIO(data)))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=90)
    return buf.getvalue()


@pytest.fixture(scope="module")
def blurry(sharp) -> bytes:
    return variant(sharp, lambda i: i.filter(ImageFilter.GaussianBlur(6)))


@pytest.fixture(scope="module")
def dark(sharp) -> bytes:
    return variant(sharp, lambda i: i.point(lambda v: v // 6))


@pytest.fixture(scope="module")
def blown(sharp) -> bytes:
    return variant(sharp, lambda i: i.point(lambda v: min(255, v * 5)))


def test_a_sharp_photo_beats_a_blurred_one(sharp, blurry):
    assert score_photo(sharp)["score"] > score_photo(blurry)["score"]


def test_sharpness_is_what_separates_them(sharp, blurry):
    # Blur destroys the edges SF3D reconstructs from; that must be the signal.
    assert score_photo(sharp)["sharpness"] > score_photo(blurry)["sharpness"] * 3


def test_well_exposed_beats_crushed_and_blown(sharp, dark, blown):
    good = score_photo(sharp)["exposure"]
    assert good > score_photo(dark)["exposure"]
    assert good > score_photo(blown)["exposure"]


def test_the_best_photo_wins_regardless_of_upload_order(sharp, blurry, dark):
    # The browser hands files over in arbitrary order; the worst must not win
    # just for being first.
    for order in ([blurry, dark, sharp], [sharp, blurry, dark], [dark, sharp, blurry]):
        best, scores = choose_best(order)
        assert order[best] is sharp
        assert sum(1 for s in scores if s["chosen"]) == 1


def test_a_single_photo_is_simply_chosen(sharp):
    best, scores = choose_best([sharp])
    assert best == 0
    assert scores[0]["chosen"] is True


def test_a_thumbnail_is_rejected_as_too_small(sharp):
    tiny = variant(sharp, lambda i: i.resize((80, 60)))
    s = score_photo(tiny)
    assert s["ok"] is False
    assert s["score"] == 0.0
    assert "small" in (s["error"] or "")


def test_unreadable_data_scores_zero_rather_than_raising():
    s = score_photo(b"this is not an image at all")
    assert s["ok"] is False
    assert s["score"] == 0.0
    assert s["error"]


def test_a_usable_photo_is_preferred_over_a_broken_one(sharp):
    best, _ = choose_best([b"garbage", sharp])
    assert best == 1


def test_all_unusable_falls_back_to_the_first_rather_than_failing():
    # A caller still needs something to send; refusing outright would strand it.
    best, scores = choose_best([b"garbage", b"also garbage"])
    assert best == 0
    assert scores[0]["chosen"] is True


def test_no_photos_is_a_programming_error():
    with pytest.raises(ValueError):
        choose_best([])


def test_scores_come_back_in_upload_order(sharp, blurry):
    _, scores = choose_best([blurry, sharp])
    assert scores[0]["score"] < scores[1]["score"]


def test_exif_rotation_does_not_break_scoring(sharp):
    rotated = variant(sharp, lambda i: i.rotate(90, expand=True))
    assert score_photo(rotated)["ok"] is True
