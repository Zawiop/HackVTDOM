"""Step 04 — map a World State selection to the prompt step 05 actually sends.

No external service. These five paragraphs live here and only here: 04-worldstate-prompts.md
is explicit that the frontend must not send raw prompt text for the preset path, so that
output stays consistent whichever building or user triggers it.

They are complete scene descriptions rather than short tags, written against Scorched
Nebraska's published reference art (scorchednebraska.org). Each state carries its OWN
palette — saturated green under canopy, desaturated teal under fog, warm ochre through
dust, bone-white ash — because that art is not one look: the flooded plates are cold and
teal, the ruined streets are warm and sepia. An earlier draft put "muted amber-green" on
all five, which flattened exactly the variety the spectrum exists to show. What is shared
is atmosphere: every plate is hazy, and depth reads as flattening haze rather than clear air.

Step 05 wraps whichever string comes out of here in its own building-preserving
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
            "Four centuries of forest have closed over the building. Ivy and deep moss have "
            "swallowed the facade until the concrete reads as a green mass with window openings, "
            "saplings and ferns grow out of every ledge and split in the paving, and a dense young "
            "canopy crowds right up against the walls and over the roof. Roots have cracked the "
            "slabs into fissures packed with leaf litter, the glass is long gone, and standing damp "
            "darkens the lower storeys. Saturated deep-green palette, soft diffuse daylight "
            "filtering down through the canopy in visible shafts, humid haze between the trunks, "
            "photoreal."
        ),
    },
    "flooded": {
        "label": "Flooded",
        "blurb": "Standing water claimed the ground floor and never receded.",
        "spectrumPosition": 2,
        "prompt": (
            "Water has stood against the building for generations and never drained. It reaches "
            "most of a storey up the facade, flat and still and reflecting the structure back as a "
            "dark silhouette, with a hard tide line and sheets of algae and mineral scale below it. "
            "Rust bleeds from every fixing, salvaged timber walkways and lean-tos have been lashed "
            "to the lower windows above the waterline, and reeds break the surface further out. "
            "Desaturated teal and grey-green palette, heavy low fog flattening everything behind it "
            "into silhouette, cold diffuse light, photoreal."
        ),
    },
    "scorched": {
        "label": "Scorched",
        "blurb": "Fire passed through and burnt itself out.",
        "spectrumPosition": 3,
        "prompt": (
            "Fire went through the building and burnt itself out a long time ago. Soot plumes "
            "streak the facade above every opening, the windows are empty sockets with warped "
            "frames, and whole sections of roof and floor have fallen in to leave charred beams "
            "standing against the sky. Ash has drifted against the sills, the surviving concrete is "
            "spalled and crazed, dead bare trees stand around it, and rusted-out vehicle hulks sit "
            "where they stopped. Warm ochre and sepia palette, low harsh sun burning through thick "
            "dust haze, photoreal."
        ),
    },
    "buried": {
        "label": "Buried",
        "blurb": "The ground rose and took the lower storeys.",
        "spectrumPosition": 4,
        "prompt": (
            "The ground has risen and taken the building's lower storeys. Pale grey ash and fine "
            "dust bank in smooth wind-carved drifts against the walls and spill in through whatever "
            "openings they reached, so the entrance is gone entirely and only the upper floors "
            "stand clear of the new surface. What is still exposed is bleached and scoured, edges "
            "rounded off, with only sparse dead scrub rooted in the slope. Pale grey-white and bone "
            "palette, flat cold overcast light, a fine dust haze hanging in the air, photoreal."
        ),
    },
    "petrified": {
        "label": "Petrified",
        "blurb": "Turned to mineral — one continuous rock formation.",
        "spectrumPosition": 5,
        "prompt": (
            "The building has gone to mineral. A thick pale crust has flowed down the facade like "
            "wax and set hard, blunting every detail and sealing the windows into blind hollows, "
            "and stalactite forms hang from the ledges and sills. It reads as one continuous rock "
            "formation rather than as masonry, nothing grows on it, and the ground around it has "
            "calcified into the same pale terraced shelves. Bone-white and cold grey palette, flat "
            "even light with almost no shadow, mineral dust haze, photoreal."
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
