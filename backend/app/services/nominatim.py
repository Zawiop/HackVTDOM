"""Nominatim geocoding (01-geocode-nominatim.md)."""

import asyncio
import time
from typing import Any, Dict, List, Optional

import httpx

from ..config import get_settings

_throttle_lock = asyncio.Lock()
_last_request_at = 0.0


class NominatimError(RuntimeError):
    """Nominatim was unreachable or returned an unusable response."""


async def _respect_rate_limit(min_interval: float) -> None:
    """Nominatim's policy caps interactive use at 1 request/second."""
    global _last_request_at
    async with _throttle_lock:
        elapsed = time.monotonic() - _last_request_at
        if elapsed < min_interval:
            await asyncio.sleep(min_interval - elapsed)
        _last_request_at = time.monotonic()


async def search(query: str, limit: int = 1) -> List[Dict[str, Any]]:
    settings = get_settings()
    await _respect_rate_limit(settings.nominatim_min_interval_seconds)

    url = f"{settings.nominatim_base_url}/search"
    params = {
        "q": query,
        "format": "json",
        "limit": str(limit),
        "addressdetails": "1",
    }
    headers = {
        "User-Agent": settings.nominatim_user_agent,
        "Accept": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            response = await client.get(url, params=params, headers=headers)
    except httpx.HTTPError as exc:
        raise NominatimError(f"Nominatim request failed: {exc}") from exc

    if response.status_code != 200:
        raise NominatimError(
            f"Nominatim returned HTTP {response.status_code}: {response.text[:200]}"
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise NominatimError("Nominatim returned a non-JSON body") from exc

    if not isinstance(payload, list):
        raise NominatimError(f"Nominatim returned {type(payload).__name__}, expected a list")

    return payload


def parse_bounding_box(raw: Optional[List[str]]) -> Optional[List[float]]:
    if not raw or len(raw) != 4:
        return None
    try:
        return [float(v) for v in raw]
    except (TypeError, ValueError):
        return None
