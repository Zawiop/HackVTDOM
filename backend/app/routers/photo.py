"""Step 03 path B -- the Mapillary convenience layer.

Manual upload is the required path and already works as the multipart `photo`
field on `/api/generate-image`. This route only looks for existing street-level
imagery so the user can skip uploading when there happens to be coverage.
"""

from fastapi import APIRouter, Query

from ..config import get_settings
from ..services.mapillary import fetch_mapillary_photos

router = APIRouter(tags=["photo"])


@router.get("/photo/mapillary")
async def mapillary_photos(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    radiusMeters: int | None = Query(None, ge=1, le=500),
    limit: int = Query(10, ge=1, le=50),
):
    """Nearby street-level captures, nearest first.

    Always 200. Zero photos is the expected common case for most addresses --
    `requiresManualUpload` says so, and the UI shows nothing rather than an
    error. Spec 03: "silently fall through to requiring manual upload".
    """
    return await fetch_mapillary_photos(
        lat,
        lng,
        get_settings().mapillary_access_token,
        radius_meters=radiusMeters,
        limit=limit,
    )
