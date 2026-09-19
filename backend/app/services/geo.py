"""Geodesic helpers.

Degrees-to-metres varies with latitude, so nothing here assumes a fixed
conversion factor (the same warning step 02 gives for footprint sizing).
"""
from __future__ import annotations

import math

from . import geo_math

EARTH_RADIUS_M = 6_371_008.8
VALID_RADII_M: tuple[int, ...] = (50, 100, 250)


def haversine_meters(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in metres between two WGS84 points."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def within_radius(
    origin: tuple[float, float], points: list[dict], radius_m: float,
    *, lat_key: str = "lat", lng_key: str = "lng",
) -> list[dict]:
    """Points inside radius_m of origin, nearest first, each with distance_m.

    The origin point itself (distance 0) is included; callers that want only
    neighbours filter it out by id.
    """
    lat0, lng0 = origin
    out = []
    for p in points:
        lat, lng = p.get(lat_key), p.get(lng_key)
        if lat is None or lng is None:
            continue
        d = haversine_meters(lat0, lng0, float(lat), float(lng))
        if d <= radius_m:
            out.append({**p, "distance_m": round(d, 2)})
    out.sort(key=lambda p: p["distance_m"])
    return out


def meters_per_degree(lat: float) -> tuple[float, float]:
    """(metres per degree latitude, metres per degree longitude) at `lat`.

    Note the order: this returns lat first, while `geo_math.meters_per_degree`
    returns lng first. Kept as-is because step 09's nudge math is written
    against it; the shared implementation lives in geo_math so the two can
    never drift apart.
    """
    per_lng, per_lat = geo_math.meters_per_degree(lat)
    return per_lat, per_lng


def offset_meters(lat: float, lng: float, d_north_m: float, d_east_m: float) -> tuple[float, float]:
    """Shift a coordinate by a metre offset — used by step 09's arrow-key nudge."""
    m_lat, m_lng = meters_per_degree(lat)
    return lat + d_north_m / m_lat, lng + d_east_m / m_lng
