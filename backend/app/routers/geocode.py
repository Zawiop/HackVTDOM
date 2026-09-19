"""Step 01 — address to lat/lng."""

import logging

from fastapi import APIRouter, HTTPException, Query

from ..models.contracts import GeocodeResult
from ..services import nominatim

logger = logging.getLogger(__name__)

router = APIRouter(tags=["geocode"])


@router.get("/geocode", response_model=GeocodeResult)
async def geocode(q: str = Query(..., min_length=1, description="Free-text address")):
    address = q.strip()
    if not address:
        raise HTTPException(status_code=422, detail="Query 'q' must not be blank")

    try:
        results = await nominatim.search(address, limit=1)
    except nominatim.NominatimError as exc:
        logger.warning("Geocode failed for %r: %s", address, exc)
        # The map-click path (step 02 directly) is the documented fallback.
        raise HTTPException(
            status_code=502,
            detail="Geocoding service unavailable — click the map to pick a location instead.",
        ) from exc

    # An empty array is Nominatim saying "no match", not an error.
    if not results:
        return GeocodeResult(found=False)

    top = results[0]
    try:
        lat = float(top["lat"])
        lng = float(top["lon"])
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("Geocode result missing usable coordinates: %r", top)
        raise HTTPException(
            status_code=502, detail="Geocoding service returned an unusable result."
        ) from exc

    place_id = top.get("place_id")
    return GeocodeResult(
        found=True,
        address=top.get("display_name"),
        lat=lat,
        lng=lng,
        placeId=int(place_id) if isinstance(place_id, (int, str)) and str(place_id).isdigit() else None,
        boundingBox=nominatim.parse_bounding_box(top.get("boundingbox")),
        addressDetails=top.get("address"),
    )
