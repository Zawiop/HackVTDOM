"""Step 04 -- the five locked presets and the freeform override (04-worldstate-prompts.md)."""
from __future__ import annotations

import json

import pytest

from app.services.worldstate import (
    WORLD_STATE_OPTIONS,
    WORLD_STATES,
    InvalidWorldStateError,
    get_preset_prompt,
    get_world_state_prompt,
    is_world_state,
)

CUSTOM = "A building made entirely of stacked vintage televisions, all switched on."


def test_exactly_the_five_locked_states():
    assert list(WORLD_STATES) == ["reclaimed", "flooded", "scorched", "buried", "petrified"]


@pytest.mark.parametrize("state", WORLD_STATES)
def test_preset_returns_its_locked_string(state):
    result = get_world_state_prompt(state)
    assert result["source"] == "preset"
    assert result["worldState"] == state
    assert result["prompt"] == get_preset_prompt(state)


@pytest.mark.parametrize("state", WORLD_STATES)
def test_presets_are_paragraphs_not_tags(state):
    # Spec 04: "a complete descriptive paragraph, not a short tag".
    prompt = get_preset_prompt(state)
    assert len(prompt) > 400
    assert prompt.count(". ") >= 4


@pytest.mark.parametrize("state", WORLD_STATES)
def test_presets_share_the_scorched_nebraska_visual_grammar(state):
    prompt = get_preset_prompt(state).lower()
    for token in ("god rays", "amber", "desaturated", "photorealistic"):
        assert token in prompt
    # Step 08 places the result on the real footprint, so the prompt must say so.
    assert "footprint" in prompt


def test_each_state_is_distinct_and_deterministic():
    prompts = [get_preset_prompt(s) for s in WORLD_STATES]
    assert len(set(prompts)) == len(WORLD_STATES)
    assert get_world_state_prompt("flooded") == get_world_state_prompt("flooded")


@pytest.mark.parametrize("bad", ["melted", "", None, "RECLAIMED"])
def test_unknown_state_is_rejected_rather_than_guessed(bad):
    with pytest.raises(InvalidWorldStateError):
        get_world_state_prompt(bad)


def test_is_world_state_guard():
    assert is_world_state("buried")
    assert not is_world_state("BURIED")
    assert not is_world_state(None)


def test_override_replaces_the_preset_rather_than_appending():
    result = get_world_state_prompt("scorched", CUSTOM)

    assert result["source"] == "override"
    assert result["prompt"] == CUSTOM
    # The critical assertion: no trace of the preset survives.
    assert get_preset_prompt("scorched") not in result["prompt"]
    assert len(result["prompt"]) == len(CUSTOM)


def test_override_works_with_no_preset_selected():
    result = get_world_state_prompt(None, CUSTOM)
    assert result["prompt"] == CUSTOM
    assert result["worldState"] is None


def test_override_remembers_which_preset_it_displaced():
    # The history row should still record what the user started from.
    assert get_world_state_prompt("buried", CUSTOM)["worldState"] == "buried"


def test_whitespace_only_override_falls_back_to_the_preset():
    result = get_world_state_prompt("flooded", "   \n  ")
    assert result["source"] == "preset"
    assert result["prompt"] == get_preset_prompt("flooded")


def test_override_is_trimmed():
    assert get_world_state_prompt(None, f"  {CUSTOM}  ")["prompt"] == CUSTOM


def test_override_does_not_require_a_valid_preset():
    assert get_world_state_prompt("nonsense", CUSTOM)["prompt"] == CUSTOM


def test_ui_options_never_carry_the_locked_prompt_text():
    assert len(WORLD_STATE_OPTIONS) == len(WORLD_STATES)
    for option in WORLD_STATE_OPTIONS:
        serialised = json.dumps(option)
        assert "god rays" not in serialised
        assert len(option["blurb"]) < 120
        assert option["blurb"] != get_preset_prompt(option["id"])


def test_spectrum_is_ordered_present_to_collapsed():
    positions = [o["spectrumPosition"] for o in WORLD_STATE_OPTIONS]
    assert positions == sorted(positions)


# --- HTTP surface ---------------------------------------------------------


def test_list_route_returns_options_without_prompt_text(client):
    res = client.get("/api/worldstates")
    assert res.status_code == 200

    body = res.json()
    assert [s["id"] for s in body["states"]] == list(WORLD_STATES)
    assert body["spectrum"] == {"from": "Present", "to": "Collapsed"}
    # The whole point of keeping the strings server-side.
    assert "god rays" not in res.text


def test_resolve_route_returns_the_preset(client):
    res = client.post("/api/worldstates/resolve", json={"worldState": "scorched"})
    assert res.status_code == 200
    assert res.json()["prompt"] == get_preset_prompt("scorched")


def test_resolve_route_honours_the_override(client):
    res = client.post(
        "/api/worldstates/resolve",
        json={"worldState": "scorched", "freeformOverride": CUSTOM},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["prompt"] == CUSTOM
    assert body["source"] == "override"


def test_resolve_route_rejects_an_unknown_state(client):
    res = client.post("/api/worldstates/resolve", json={"worldState": "melted"})
    assert res.status_code == 400
    assert "reclaimed" in res.json()["detail"]["accepted"]


def test_the_step_04_stub_is_gone(client):
    # It used to return 501 pointing at the spec file.
    assert client.get("/api/worldstates").status_code == 200
