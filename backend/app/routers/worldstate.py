"""Step 04 — the World State spectrum the picker renders."""

from typing import List

from fastapi import APIRouter

from ..models.contracts import WorldStateOption
from ..services import worldstate

router = APIRouter(tags=["worldstate"])


@router.get("/worldstates", response_model=List[WorldStateOption])
async def world_states():
    """Ordered Present -> Collapsed. The prompt text stays server-side by design."""
    return worldstate.options()
