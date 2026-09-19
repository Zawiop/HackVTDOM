"""Routes nobody has implemented yet.

Each exists so the API surface is complete and the frontend gets an honest 501
instead of a 404. Replace the body when you pick one up — see the spec file.
"""

from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["not-implemented"])

_OWNERS = {
    "/photo/mapillary": "03-photo-input.md",
    "/worldstates": "04-worldstate-prompts.md",
    "/placement": "08-placement-transform.md",
}


def _pending(path: str):
    raise HTTPException(
        status_code=501,
        detail=f"Not implemented yet — see markdown_files/{_OWNERS[path]}",
    )


@router.get("/photo/mapillary")
async def mapillary_photos():
    """Step 03's optional convenience layer. Manual upload already works via
    /generate-image's multipart `photo` field, which is the required path."""
    _pending("/photo/mapillary")


@router.get("/worldstates")
async def world_states():
    """Step 04. Until this lands the frontend sends raw prompt text, which
    04-worldstate-prompts.md says must not happen for the five presets."""
    _pending("/worldstates")


@router.post("/placement")
async def compute_placement():
    """Step 08 — the rotation/scale/ground-alignment core. Nothing computes a
    real transform yet, so rows are written with step 08's defaults."""
    _pending("/placement")
