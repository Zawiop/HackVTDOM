"""In-memory footprint cache keyed by rounded coordinates.

02-footprint-overpass.md requires caching every successful Overpass response so
demo day never depends on the public instance answering live. Four decimal
places is roughly 11 m, which stays inside a single building footprint while
still absorbing the small coordinate jitter between a geocode and a map click.
"""

from typing import Any, Dict, Optional, Tuple

COORD_PRECISION = 4

_store: Dict[Tuple[float, float, int], Any] = {}


def make_key(lat: float, lng: float, radius_meters: int) -> Tuple[float, float, int]:
    return (round(lat, COORD_PRECISION), round(lng, COORD_PRECISION), radius_meters)


def get(lat: float, lng: float, radius_meters: int) -> Optional[Any]:
    return _store.get(make_key(lat, lng, radius_meters))


def put(lat: float, lng: float, radius_meters: int, value: Any) -> None:
    _store[make_key(lat, lng, radius_meters)] = value


def clear() -> None:
    _store.clear()


def size() -> int:
    return len(_store)
