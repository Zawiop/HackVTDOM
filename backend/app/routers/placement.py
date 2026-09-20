"""Step 08 — compute the transform that puts a mesh on its real footprint."""

import logging

from fastapi import APIRouter, HTTPException

from ..models.contracts import PlacementRequest, PlacementResult
from ..services import placement as placement_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["placement"])


@router.post("/placement", response_model=PlacementResult)
async def compute_placement(request: PlacementRequest):
    polygon = [(p[0], p[1]) for p in request.footprint.geometry]
    if len(polygon) < 3:
        raise HTTPException(status_code=422, detail="footprint.geometry needs at least 3 points")

    neighbors = [
        [(p[0], p[1]) for p in n.geometry]
        for n in request.neighbors
        if n.osmId != request.footprint.osmId and len(n.geometry) >= 3
    ]

    try:
        result = placement_service.compute_placement(
            polygon_lnglat=polygon,
            base_bearing_degrees=request.footprint.rotationDegrees,
            mesh_width_meters=request.meshExtentsMeters.width,
            mesh_depth_meters=request.meshExtentsMeters.depth,
            neighbors_lnglat=neighbors,
            footprint_confidence=request.footprintConfidence,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return PlacementResult(**result)
