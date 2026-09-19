"""Step 02 route. The resolution logic lives in services/footprint.py."""

import logging

from fastapi import APIRouter, HTTPException

from ..models.contracts import FootprintRequest, FootprintResult
from ..services import footprint as footprint_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["footprint"])


@router.post("/footprint", response_model=FootprintResult)
async def footprint(request: FootprintRequest):
    try:
        return await footprint_service.lookup(request.lat, request.lng, request.radiusMeters)
    except footprint_service.FootprintUnavailable as exc:
        raise HTTPException(
            status_code=502,
            detail="Building footprint service unavailable. Try again in a moment.",
        ) from exc
