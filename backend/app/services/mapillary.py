"""Step 03 path B -- Mapillary auto-fetch (03-photo-input.md).

A convenience layer, not the fallback of last resort. Manual upload is the
required path and already works through `/api/generate-image`'s multipart field;
this only saves the user a step when there happens to be street-level coverage.

An empty result is the normal, expected outcome for most addresses, so nothing
here raises and nothing produces a user-facing error state.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from .geo import haversine_meters
from .geo_math import meters_per_degree

log = logging.getLogger("scorched.mapillary")

MAPILLARY_IMAGES_URL = "https://graph.mapillary.com/images"

# Field names verified live 2026-09-19 -- see VERIFIED CAPTURE in 03-photo-input.md.
FIELDS = "id,thumb_2048_url,thumb_1024_url,geometry,captured_at"

# Spec 03 says "a small box (~30-50m)"; 40 m is the middle of that range.
DEFAULT_RADIUS_METERS = 40

# Verified live: graph.mapillary.com returns *non-deterministic* counts for
# byte-identical bbox queries -- five consecutive identical requests to a known
# dense area returned 0, 2, 5, 6, 5 images. So a single empty `data` array is
# frequently a false negative rather than genuine absence of coverage.
#
# The fix is to retry at the spec'd radius before concluding "no imagery", then
# make one wider pass. Widening is deliberately last and modest: imagery 100 m
# away may well be of a different building, and this photo feeds image
# generation, so relevance matters more than hit rate. Results are ranked by
# true distance so the nearest capture always wins.
ATTEMPT_RADII = (DEFAULT_RADIUS_METERS, DEFAULT_RADIUS_METERS, 100)

TIMEOUT_S = 8.0


def bbox_around(lat: float, lng: float, meters: float) -> str:
    """Mapillary wants `minLng,minLat,maxLng,maxLat` as a bare comma string."""
    per_lng, per_lat = meters_per_degree(lat)
    d_lat = meters / per_lat
    d_lng = meters / per_lng
    return ",".join(
        f"{v:.7f}" for v in (lng - d_lng, lat - d_lat, lng + d_lng, lat + d_lat)
    )




def _to_photo(img: Dict[str, Any], lat: float, lng: float) -> Optional[Dict[str, Any]]:
    url = img.get("thumb_2048_url") or img.get("thumb_1024_url")
    if not url:
        return None

    coords = (img.get("geometry") or {}).get("coordinates")
    # Mapillary geometry is GeoJSON order: [lng, lat].
    location = (
        {"lat": float(coords[1]), "lng": float(coords[0])}
        if isinstance(coords, (list, tuple)) and len(coords) == 2
        else None
    )

    captured = img.get("captured_at")
    return {
        "source": "mapillary",
        "id": str(img.get("id")),
        "url": url,
        "mimeType": "image/jpeg",
        # captured_at is epoch MILLISECONDS (1631875240000 -> 2021-09-17).
        "capturedAt": int(captured) if isinstance(captured, (int, float)) else None,
        "location": location,
        "distanceMeters": (
            haversine_meters(lat, lng, location["lat"], location["lng"]) if location else None
        ),
    }


async def fetch_mapillary_photos(
    lat: float,
    lng: float,
    token: Optional[str],
    radius_meters: Optional[int] = None,
    limit: int = 10,
) -> Dict[str, Any]:
    """Look for street-level imagery near a point. Never raises."""
    if not token:
        return {"attempted": False, "photos": [], "attempts": 0, "requiresManualUpload": True}

    # An explicit radius from the caller disables the widening ladder -- they
    # asked for a specific box -- but still retries through the flaky index.
    radii = (radius_meters, radius_meters) if radius_meters else ATTEMPT_RADII

    by_id: Dict[str, Dict[str, Any]] = {}
    last_bbox: Optional[str] = None
    last_error: Optional[str] = None
    attempts = 0

    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        for radius in radii:
            attempts += 1
            last_bbox = bbox_around(lat, lng, radius)
            try:
                res = await client.get(
                    MAPILLARY_IMAGES_URL,
                    params={"fields": FIELDS, "bbox": last_bbox, "limit": limit},
                    # Token as a header rather than a query param, so it never
                    # lands in a proxy or access log. Spec 03 permits either.
                    headers={"Authorization": f"OAuth {token}"},
                )
                res.raise_for_status()
                for img in (res.json() or {}).get("data") or []:
                    photo = _to_photo(img, lat, lng)
                    if photo and photo["id"] not in by_id:
                        by_id[photo["id"]] = photo
                # Stop at the first non-empty result; the extra passes exist to
                # beat the flaky index, not to vacuum up every photo in the area.
                if by_id:
                    break
            except Exception as exc:  # network, HTTP, malformed JSON
                last_error = f"{type(exc).__name__}: {exc}"
                log.info("mapillary attempt %d failed: %s", attempts, last_error)

    photos: List[Dict[str, Any]] = sorted(
        by_id.values(),
        key=lambda p: (
            p["distanceMeters"] if p["distanceMeters"] is not None else float("inf"),
            -(p["capturedAt"] or 0),
        ),
    )

    result: Dict[str, Any] = {
        "attempted": True,
        "photos": photos,
        "attempts": attempts,
        "bbox": last_bbox,
        # Zero photos is the expected common case, never an error state. The
        # caller just falls through to requiring a manual upload.
        "requiresManualUpload": not photos,
    }
    # Diagnostic only; present alongside photos:[] does not mean "show an error".
    if not photos and last_error:
        result["error"] = last_error
    return result
