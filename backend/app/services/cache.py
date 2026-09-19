"""Footprint cache, keyed by rounded coordinates and persisted to disk.

02-footprint-overpass.md requires caching every successful Overpass response so
demo day never depends on the public instance answering live. Four decimal
places is roughly 11 m, which stays inside a single building footprint while
still absorbing the small coordinate jitter between a geocode and a map click.

It is written through to a JSON file because the reason the cache exists is
demo-day reliability, and an in-memory cache dies with the server — the pre-baked
buildings would be gone exactly when Overpass is least likely to answer. Every
public Overpass endpoint was down at some point during this build.
"""

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

COORD_PRECISION = 4

BACKEND_DIR = Path(__file__).resolve().parents[2]
CACHE_PATH = Path(
    os.environ.get("FOOTPRINT_CACHE_PATH", BACKEND_DIR / ".cache" / "footprints.json")
)

Key = Tuple[float, float, int]

_store: Dict[Key, Any] = {}
_loaded = False


def make_key(lat: float, lng: float, radius_meters: int) -> Key:
    return (round(lat, COORD_PRECISION), round(lng, COORD_PRECISION), radius_meters)


def get(lat: float, lng: float, radius_meters: int) -> Optional[Any]:
    _ensure_loaded()
    return _store.get(make_key(lat, lng, radius_meters))


def put(lat: float, lng: float, radius_meters: int, value: Any) -> None:
    _ensure_loaded()
    _store[make_key(lat, lng, radius_meters)] = value
    _save()


def clear() -> None:
    global _loaded
    _store.clear()
    _loaded = True  # an explicit clear must not be undone by a later lazy load
    _save()


def size() -> int:
    _ensure_loaded()
    return len(_store)


def _ensure_loaded() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        raw = json.loads(CACHE_PATH.read_text())
    except FileNotFoundError:
        return
    except (OSError, ValueError) as exc:
        # A corrupt cache must never take the API down with it.
        logger.warning("Ignoring unreadable footprint cache at %s: %s", CACHE_PATH, exc)
        return

    for entry in raw.get("entries", []):
        try:
            _store[(entry["lat"], entry["lng"], entry["radius"])] = (
                entry["elements"],
                entry["source"],
            )
        except (KeyError, TypeError):
            continue
    logger.info("Loaded %d cached footprints from %s", len(_store), CACHE_PATH)


def _save() -> None:
    payload = {
        "entries": [
            {
                "lat": lat,
                "lng": lng,
                "radius": radius,
                "elements": value[0],
                "source": value[1],
            }
            for (lat, lng, radius), value in _store.items()
        ]
    }
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        # Write-and-rename so a crash mid-write cannot leave a half-file behind.
        with tempfile.NamedTemporaryFile(
            "w", dir=CACHE_PATH.parent, delete=False, encoding="utf-8"
        ) as handle:
            json.dump(payload, handle)
            temp = Path(handle.name)
        temp.replace(CACHE_PATH)
    except OSError as exc:
        logger.warning("Could not persist footprint cache to %s: %s", CACHE_PATH, exc)
