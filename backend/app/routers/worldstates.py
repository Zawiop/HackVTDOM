"""Step 04 -- World State presets and the freeform override.

Note what is NOT here: any endpoint that hands the five locked prompt strings to
the browser, and any endpoint that accepts prompt text for the preset path.
Spec 04 requires those strings stay server-side so output is consistent
regardless of which building or user triggers them.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services.worldstate import (
    WORLD_STATE_OPTIONS,
    WORLD_STATES,
    InvalidWorldStateError,
    get_world_state_prompt,
)

router = APIRouter(tags=["worldstate"])


class WorldStateResolveRequest(BaseModel):
    worldState: Optional[str] = None
    # When non-empty this REPLACES the locked preset string for one generation.
    freeformOverride: Optional[str] = None


@router.get("/worldstates")
async def world_states():
    """Spectrum options for the UI. Labels and blurbs only -- no prompt text."""
    return {
        "states": WORLD_STATE_OPTIONS,
        "order": list(WORLD_STATES),
        "spectrum": {"from": "Present", "to": "Collapsed"},
    }


@router.post("/worldstates/resolve")
async def resolve_world_state(request: WorldStateResolveRequest):
    """Return the single string step 05 sends to the image model."""
    try:
        return get_world_state_prompt(request.worldState, request.freeformOverride)
    except InvalidWorldStateError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error": f"Unknown world state {exc.args[0]!r}.",
                "accepted": list(WORLD_STATES),
            },
        ) from exc
