"""Routes nobody has implemented yet.

Each exists so the API surface is complete and the frontend gets an honest 501
instead of a 404. Replace the body when you pick one up — see the spec file.
"""

from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["not-implemented"])

_OWNERS: dict[str, str] = {}
# Steps 03 (photo/mapillary), 04 (worldstates) and 08 (placement) used to live
# here. They are implemented now -- see routers/photo.py, routers/worldstates.py
# and routers/placement.py. The router stays so the next unimplemented step has
# somewhere honest to go.


def _pending(path: str):
    raise HTTPException(
        status_code=501,
        detail=f"Not implemented yet - see markdown_files/{_OWNERS[path]}",
    )
