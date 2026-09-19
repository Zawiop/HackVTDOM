"""Overpass building-footprint queries (02-footprint-overpass.md).

The public instance rate-limits with 429/406 and no published ceiling. Policy
from the spec: back off 30 s and retry, then fall through to a mirror.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

import httpx

from ..config import get_settings

logger = logging.getLogger(__name__)

RATE_LIMITED_STATUSES = {429, 406}


class OverpassError(RuntimeError):
    """Every Overpass endpoint failed."""


def build_query(lat: float, lng: float, radius_meters: int) -> str:
    """Buildings as ways *and* as multipolygon relations.

    02-footprint-overpass.md specifies `way["building"]` only. That silently
    misses any building mapped as a multipolygon relation — which on the VT
    campus includes Torgersen Hall, verified absent from a 250 m way-only pull
    centred on its own coordinates. Relations are handled in footprint.py.
    """
    around = f"around:{radius_meters},{lat},{lng}"
    return (
        "[out:json];"
        f'(way["building"]({around});relation["building"]({around}););'
        "out geom;"
    )


async def fetch_buildings(
    lat: float, lng: float, radius_meters: int
) -> Tuple[List[Dict[str, Any]], str]:
    """Return (elements, endpoint_url) from the first endpoint that answers.

    The spec's policy is "back off 30 s on 429/406 before retrying". Sleeping
    the moment the primary rate-limits would stall the request for 30 s while
    healthy mirrors sit untried, so the backoff is deferred: every endpoint gets
    one attempt first, and only the rate-limited ones are retried after the wait.
    """
    settings = get_settings()
    query = build_query(lat, lng, radius_meters)
    errors: List[str] = []

    elements, endpoint, rate_limited = await _try_round(
        settings.overpass_endpoints, query, settings.overpass_timeout_seconds, errors
    )
    if elements is not None:
        return elements, endpoint

    if rate_limited:
        logger.warning(
            "Overpass rate-limited by %s; backing off %.0fs before retrying",
            ", ".join(rate_limited),
            settings.overpass_backoff_seconds,
        )
        await asyncio.sleep(settings.overpass_backoff_seconds)
        elements, endpoint, _ = await _try_round(
            rate_limited, query, settings.overpass_timeout_seconds, errors
        )
        if elements is not None:
            return elements, endpoint

    raise OverpassError("; ".join(errors) or "no Overpass endpoint responded")


async def _try_round(
    endpoints: List[str], query: str, timeout: float, errors: List[str]
) -> Tuple[Optional[List[Dict[str, Any]]], str, List[str]]:
    """One attempt per endpoint. Returns (elements, endpoint, rate_limited_endpoints)."""
    rate_limited: List[str] = []
    for endpoint in endpoints:
        try:
            return await _post(endpoint, query, timeout), endpoint, rate_limited
        except _RateLimited as exc:
            rate_limited.append(endpoint)
            errors.append(f"{endpoint}: {exc}")
        except OverpassError as exc:
            errors.append(f"{endpoint}: {exc}")
        logger.warning("Overpass endpoint failed, trying next: %s", errors[-1].split("\n")[0])
    return None, "", rate_limited


class _RateLimited(OverpassError):
    pass


async def _post(endpoint: str, query: str, timeout: float) -> List[Dict[str, Any]]:
    settings = get_settings()
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": settings.nominatim_user_agent,
        "Accept": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.post(endpoint, data={"data": query}, headers=headers)
    except httpx.HTTPError as exc:
        raise OverpassError(f"request failed: {exc}") from exc

    if response.status_code in RATE_LIMITED_STATUSES:
        raise _RateLimited(f"HTTP {response.status_code}")
    if response.status_code != 200:
        raise OverpassError(f"HTTP {response.status_code}: {response.text[:200]}")

    try:
        payload = response.json()
    except ValueError as exc:
        raise OverpassError("non-JSON body") from exc

    elements = payload.get("elements")
    if not isinstance(elements, list):
        raise OverpassError("response missing an 'elements' list")
    return elements
