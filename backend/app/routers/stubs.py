"""Routes nobody has implemented yet.

Each exists so the API surface is complete and the frontend gets an honest 501
instead of a 404. Replace the body when you pick one up — see the spec file.

Empty right now: steps 01-13 all have real routes. The router stays mounted so
the next unimplemented step has somewhere honest to go.
"""

from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["not-implemented"])

_OWNERS: dict[str, str] = {}


def _pending(path: str):
    raise HTTPException(
        status_code=501,
        detail=f"Not implemented yet — see markdown_files/{_OWNERS[path]}",
    )
