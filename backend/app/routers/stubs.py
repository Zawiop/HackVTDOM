"""Placeholders for modules owned by other teammates.

Each route exists so the frontend and the API contract are complete from day one;
the owner replaces the body. Do not implement these here — see the named spec file.
"""

from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["not-implemented"])

_OWNERS = {
    "/photo/mapillary": "03-photo-input.md",
    "/photo/upload": "03-photo-input.md",
    "/worldstates": "04-worldstate-prompts.md",
    "/generate/image": "05-image-edit-gemini.md",
    "/generate/mesh": "06-mesh-generate-triposr.md",
    "/mesh/normalize": "07-mesh-normalize.md",
    "/placement": "08-placement-transform.md",
    "/generations": "11-persistence-supabase.md",
    "/propagate": "10-propagate.md",
}


def _pending(path: str):
    raise HTTPException(
        status_code=501,
        detail=f"Not implemented yet — see markdown_files/{_OWNERS[path]}",
    )


@router.get("/photo/mapillary")
async def mapillary_photos():
    _pending("/photo/mapillary")


@router.post("/photo/upload")
async def upload_photo():
    _pending("/photo/upload")


@router.get("/worldstates")
async def world_states():
    _pending("/worldstates")


@router.post("/generate/image")
async def generate_image():
    _pending("/generate/image")


@router.post("/generate/mesh")
async def generate_mesh():
    _pending("/generate/mesh")


@router.post("/mesh/normalize")
async def normalize_mesh():
    _pending("/mesh/normalize")


@router.post("/placement")
async def compute_placement():
    _pending("/placement")


@router.get("/generations")
async def list_generations():
    _pending("/generations")


@router.post("/generations")
async def save_generation():
    _pending("/generations")


@router.post("/propagate")
async def propagate():
    _pending("/propagate")
