"""Step 04 — map a World State selection to the prompt step 05 actually sends.

No external service. These five paragraphs live here and only here: 04-worldstate-prompts.md
is explicit that the frontend must not send raw prompt text for the preset path, so that
output stays consistent whichever building or user triggers it.

They are written as complete scene descriptions rather than short tags, tuned to Scorched
Nebraska's reference art — overgrowth, cracked concrete, god rays, a muted amber-green
palette. Step 05 wraps whichever string comes out of here in its own building-preserving
instruction, so these describe condition and surroundings only, never the architecture.

The UI presents them as a Present <-> Collapsed spectrum rather than a filter picker;
`spectrumPosition` is that ordering, from least to most transformed.
"""

from typing import Dict, List, Optional, Tuple

MAX_OVERRIDE_CHARS = 4000

_PRESETS: Dict[str, dict] = {
    "reclaimed": {
        "label": "Reclaimed",
        "blurb": "Intact, but wholly surrendered to plant life.",
        "spectrumPosition": 1,
        "prompt": (
            "Decades after the last people left, the building stands intact but wholly "
            "surrendered to plant life. Thick moss and dark ivy climb the facade and soften "
            "every edge, saplings and tall grass push up through split paving, and root "
            "systems have cracked the concrete into a web of fissures packed with earth. "
            "Windows are empty or clouded, gutters have become planters, and a canopy of "
            "young trees crowds the structure. Shafts of hazy god rays fall through the "
            "leaves onto the walls. Muted amber-green palette, overcast diffuse light, "
            "desaturated and quiet, photoreal."
        ),
    },
    "flooded": {
        "label": "Flooded",
        "blurb": "Standing water claimed the ground floor and never receded.",
        "spectrumPosition": 2,
        "prompt": (
            "Standing water has claimed the ground floor and never receded. A dark tide line "
            "stains the facade a storey up; below it the masonry is slick with algae and "
            "mineral scale, and the still brown-green surface mirrors the building back at "
            "itself. Reeds and water plants have colonised the shallows, debris has collected "
            "against the walls, and rust bleeds from every fixing. Damp has bloomed across the "
            "upper walls. Muted amber-green palette, heavy humid air, god rays breaking "
            "through low cloud onto the water, photoreal."
        ),
    },
    "scorched": {
        "label": "Scorched",
        "blurb": "Fire passed through and burnt itself out.",
        "spectrumPosition": 3,
        "prompt": (
            "Fire has passed through and burnt itself out. The facade is streaked with soot "
            "above every opening, window glass is gone and the frames are warped, and sections "
            "of roof and floor have collapsed inward leaving charred beams exposed against the "
            "sky. Ash has settled in drifts along the sills and the ground, the surviving "
            "concrete is spalled and crazed, and thin smoke still hangs in the air. Scorched "
            "amber and grey-green palette, low harsh sun, god rays cutting through the haze "
            "and the gaps in the structure, photoreal."
        ),
    },
    "buried": {
        "label": "Buried",
        "blurb": "The ground rose and took the lower storeys.",
        "spectrumPosition": 4,
        "prompt": (
            "The earth has risen and taken the lower storeys. Drifts of soil and fine sand "
            "bank steeply against the walls and pour in through the openings they have "
            "reached, burying the entrance entirely and leaving only the upper floors above "
            "the new ground line. Coarse grass and scrub have rooted across the slope as if it "
            "had always been a hillside, and the exposed concrete is wind-scoured and cracked. "
            "Muted amber-green palette, dusty air, god rays raking low across the dunes, "
            "photoreal."
        ),
    },
    "petrified": {
        "label": "Petrified",
        "blurb": "Turned to mineral — one continuous rock formation.",
        "spectrumPosition": 5,
        "prompt": (
            "The building has turned to mineral. Every surface is crusted in a thick pale "
            "calcite shell that has flowed down the facade like candle wax and set, blunting "
            "the detail and sealing the windows into blind hollows. Stalactite forms hang from "
            "the ledges, the whole structure reads as one continuous grey-white rock formation "
            "rather than as masonry, and nothing grows on it. A few streaks of amber-green "
            "lichen cling to the sheltered faces. Muted amber-green palette, flat cold light, "
            "god rays through mineral dust, photoreal."
        ),
    },
}

WORLD_STATE_IDS: Tuple[str, ...] = tuple(
    sorted(_PRESETS, key=lambda k: _PRESETS[k]["spectrumPosition"])
)


class UnknownWorldState(ValueError):
    pass


class OverrideTooLong(ValueError):
    pass


def options() -> List[dict]:
    """The spectrum, for the picker. Deliberately without the prompt text.

    Handing the locked strings to the browser invites a client to send one back as a
    freeform override, which is exactly the inconsistency keeping them server-side prevents.
    """
    return [
        {
            "id": key,
            "label": preset["label"],
            "blurb": preset["blurb"],
            "spectrumPosition": preset["spectrumPosition"],
        }
        for key, preset in sorted(_PRESETS.items(), key=lambda kv: kv[1]["spectrumPosition"])
    ]


def prompt_for(world_state: str) -> str:
    try:
        return _PRESETS[world_state]["prompt"]
    except KeyError:
        raise UnknownWorldState(
            f"unknown worldState {world_state!r}; expected one of {', '.join(WORLD_STATE_IDS)}"
        ) from None


def resolve(world_state: Optional[str], override: Optional[str]) -> Tuple[str, str, Optional[str]]:
    """Return (prompt, source, world_state_id) for one generation.

    A freeform override *replaces* the locked string rather than appending to it — that
    replacement is the part that literally satisfies "describe desired changes with an AI
    prompt", since a user picking a preset button is not the one doing the describing.
    """
    override = (override or "").strip()
    world_state = (world_state or "").strip() or None

    if override:
        if len(override) > MAX_OVERRIDE_CHARS:
            raise OverrideTooLong(
                f"freeform description is longer than {MAX_OVERRIDE_CHARS} characters"
            )
        # The id is still reported so the row records which button it replaced.
        return override, "override", world_state if world_state in _PRESETS else None

    if world_state is None:
        raise UnknownWorldState(
            "expected a 'worldState' from "
            f"{', '.join(WORLD_STATE_IDS)}, or a freeform 'worldStatePrompt'"
        )

    return prompt_for(world_state), f"preset:{world_state}", world_state
