"""Step 04 — the locked presets, the override rule, and the spectrum."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import worldstate

client = TestClient(app)


def test_all_five_spectrum_points_exist():
    ids = [o["id"] for o in worldstate.options()]
    assert ids == ["reclaimed", "flooded", "scorched", "buried", "petrified"]


def test_options_are_ordered_present_to_collapsed():
    positions = [o["spectrumPosition"] for o in worldstate.options()]
    assert positions == sorted(positions)
    assert positions == [1, 2, 3, 4, 5]


def test_options_never_leak_the_locked_prompt_text():
    """Handing the strings to the browser invites a client to echo one back as an override."""
    for option in worldstate.options():
        assert "prompt" not in option
        assert set(option) == {"id", "label", "blurb", "spectrumPosition"}


def test_presets_are_full_descriptions_not_tags():
    for state in worldstate.WORLD_STATE_IDS:
        prompt = worldstate.prompt_for(state)
        assert len(prompt) > 300, state
        assert prompt.count(".") >= 3, state  # a paragraph, not a phrase


def test_presets_share_the_reference_art_direction():
    for state in worldstate.WORLD_STATE_IDS:
        prompt = worldstate.prompt_for(state).lower()
        assert "god ray" in prompt, state
        assert "palette" in prompt, state
        assert "photoreal" in prompt, state


def test_preset_resolves_to_its_locked_string():
    prompt, source, state = worldstate.resolve("flooded", None)

    assert prompt == worldstate.prompt_for("flooded")
    assert source == "preset:flooded"
    assert state == "flooded"


def test_same_preset_is_identical_for_every_caller():
    """The whole reason the strings live server-side."""
    assert worldstate.resolve("scorched", None)[0] == worldstate.resolve("scorched", "")[0]


def test_override_replaces_the_preset_rather_than_appending():
    locked = worldstate.prompt_for("reclaimed")
    prompt, source, state = worldstate.resolve("reclaimed", "knee-deep in wildflowers")

    assert prompt == "knee-deep in wildflowers"
    assert locked not in prompt
    assert source == "override"
    # The id is still recorded, so the row knows which button was overridden.
    assert state == "reclaimed"


def test_override_works_without_any_preset_selected():
    prompt, source, state = worldstate.resolve(None, "swallowed by a glacier")

    assert prompt == "swallowed by a glacier"
    assert source == "override"
    assert state is None


def test_blank_override_falls_through_to_the_preset():
    prompt, source, _ = worldstate.resolve("buried", "   ")
    assert prompt == worldstate.prompt_for("buried")
    assert source == "preset:buried"


def test_unknown_world_state_is_rejected():
    with pytest.raises(worldstate.UnknownWorldState):
        worldstate.resolve("radioactive", None)


def test_nothing_selected_is_rejected():
    with pytest.raises(worldstate.UnknownWorldState):
        worldstate.resolve(None, None)


def test_oversized_override_is_rejected():
    with pytest.raises(worldstate.OverrideTooLong):
        worldstate.resolve(None, "x" * (worldstate.MAX_OVERRIDE_CHARS + 1))


# --- route ---


def test_worldstates_route_returns_the_spectrum():
    response = client.get("/api/worldstates")
    assert response.status_code == 200

    body = response.json()
    assert len(body) == 5
    assert [o["id"] for o in body] == list(worldstate.WORLD_STATE_IDS)
    assert all(o["label"] and o["blurb"] for o in body)
    assert all("prompt" not in o for o in body)


def test_generate_image_rejects_an_unknown_world_state():
    response = client.post(
        "/api/generate-image",
        files={"photo": ("b.jpg", b"not-really-an-image", "image/jpeg")},
        data={"worldState": "radioactive"},
    )
    assert response.status_code == 400
    assert "radioactive" in response.json()["detail"]


def test_generate_image_requires_a_world_state():
    response = client.post(
        "/api/generate-image",
        files={"photo": ("b.jpg", b"not-really-an-image", "image/jpeg")},
    )
    assert response.status_code == 400
    assert "worldState" in response.json()["detail"]
