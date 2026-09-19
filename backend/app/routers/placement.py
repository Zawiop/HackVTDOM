"""Step 08 -- the placement transform.

Takes step 02's footprint result (including the neighbours it already fetched)
and step 07's normalized mesh, and returns the transform record. Nothing here
calls Overpass: spec 08 requires the neighbours be reused, not re-fetched.
"""

import base64
import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from ..generation import storage
from ..services.placement import PlacementInputError, compute_placement_transform

logger = logging.getLogger(__name__)

router = APIRouter(tags=["placement"])

MESH_FETCH_TIMEOUT_S = 30.0


class PlacementFootprint(BaseModel):
    """Step 02's result, or just the parts of it step 08 needs."""

    model_config = ConfigDict(extra="allow")

    polygon: Optional[Dict[str, Any]] = None
    # Accepted as an alias so a whole FootprintResult can be posted verbatim.
    selected: Optional[Dict[str, Any]] = None
    neighbors: List[Dict[str, Any]] = []
    confidence: Optional[str] = None


class PlacementMesh(BaseModel):
    model_config = ConfigDict(extra="allow")

    # Any of these; meshUrl is what step 06/07 actually return.
    meshUrl: Optional[str] = None
    path: Optional[str] = None
    bytesBase64: Optional[str] = None
    upAxis: str = "y"
    baseOutline: Optional[List[List[float]]] = None


class PlacementRequest(BaseModel):
    footprint: PlacementFootprint
    mesh: PlacementMesh
    options: Optional[Dict[str, float]] = None


async def _resolve_mesh_bytes(mesh: PlacementMesh) -> Dict[str, Any]:
    """Turn whatever the caller gave us into something the service can read."""
    if mesh.baseOutline:
        return mesh.model_dump(exclude_none=True)

    if mesh.bytesBase64 is not None:
        data = base64.b64decode(mesh.bytesBase64, validate=False)
        # b64decode yields empty bytes for junk input, which would otherwise
        # fall through to a (probably absent) path and surface as a confusing
        # file-not-found.
        if not data:
            raise HTTPException(status_code=400, detail='"mesh.bytesBase64" decoded to zero bytes.')
        return {"bytes": data, "path": mesh.path or "mesh.glb", "upAxis": mesh.upAxis}

    if mesh.path:
        return {"path": mesh.path, "upAxis": mesh.upAxis}

    if mesh.meshUrl:
        # A meshUrl this backend served itself is on disk; read it directly
        # rather than making the server fetch from itself.
        local = storage.local_path_for_url(mesh.meshUrl)
        if local is not None:
            return {"path": str(local), "upAxis": mesh.upAxis}

        parsed = urlparse(mesh.meshUrl)
        if parsed.scheme in ("http", "https"):
            async with httpx.AsyncClient(timeout=MESH_FETCH_TIMEOUT_S) as client:
                res = await client.get(mesh.meshUrl)
            if res.status_code != 200:
                raise HTTPException(
                    status_code=422,
                    detail=f"Could not fetch mesh: HTTP {res.status_code} from {mesh.meshUrl}",
                )
            name = parsed.path.rsplit("/", 1)[-1] or "mesh.glb"
            return {"bytes": res.content, "path": name, "upAxis": mesh.upAxis}

        return {"path": mesh.meshUrl, "upAxis": mesh.upAxis}

    raise HTTPException(
        status_code=400,
        detail='Body needs "mesh" with one of: meshUrl, path, bytesBase64, or baseOutline.',
    )


@router.post("/placement")
async def compute_placement(request: PlacementRequest):
    footprint = request.footprint.model_dump(exclude_none=True)
    if not footprint.get("polygon") and not footprint.get("selected"):
        raise HTTPException(
            status_code=400,
            detail='Body needs "footprint.polygon" (or step 02\'s "selected") with a geometry ring.',
        )

    mesh_input = await _resolve_mesh_bytes(request.mesh)

    try:
        return compute_placement_transform(footprint, mesh_input, request.options)
    except PlacementInputError as exc:
        # Bad input, not a server fault.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
