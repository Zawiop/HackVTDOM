"""Step 03 path B -- the Mapillary convenience layer (03-photo-input.md).

Live calls are marked `live` and skipped without a token, so the suite stays
green on a machine that has none. Run them with `-m live`.
"""
from __future__ import annotations

import asyncio
import math

import pytest

from app.config import get_settings
from app.services.mapillary import DEFAULT_RADIUS_METERS, bbox_around, fetch_mapillary_photos

# Real coordinates. Blacksburg coverage verified live 2026-09-19.
BURRUSS = (37.2284, -80.4234)
# Open water, hundreds of km from any road -- a genuine no-coverage control.
LAKE_SUPERIOR = (47.7, -87.5)

live = pytest.mark.live
needs_token = pytest.mark.skipif(
    not get_settings().mapillary_access_token, reason="MAPILLARY_ACCESS_TOKEN not set"
)


def _haversine(lat1, lng1, lat2, lng2):
    r = 6371008.8
    dlat, dlng = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    s = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    )
    return 2 * r * math.asin(min(1.0, math.sqrt(s)))


def test_bbox_is_actually_the_requested_size_on_the_ground():
    lat, lng = BURRUSS
    min_lng, min_lat, max_lng, max_lat = (float(v) for v in bbox_around(lat, lng, 40).split(","))

    north = _haversine(lat, lng, max_lat, lng)
    east = _haversine(lat, lng, lat, max_lng)

    assert 39 < north < 41
    assert 39 < east < 41
    assert min_lng < max_lng and min_lat < max_lat


def test_bbox_accounts_for_latitude():
    span = lambda s: float(s.split(",")[2]) - float(s.split(",")[0])
    # A degree of longitude shrinks toward the poles, so the same 100 m needs
    # more than twice the degree span at 70 north as at the equator.
    assert span(bbox_around(70, 0, 100)) > span(bbox_around(0, 0, 100)) * 2


def test_bbox_is_in_mapillary_order():
    parts = bbox_around(*BURRUSS, 40).split(",")
    assert len(parts) == 4
    assert float(parts[1]) == pytest.approx(BURRUSS[0], abs=0.01)  # minLat
    assert float(parts[0]) == pytest.approx(BURRUSS[1], abs=0.01)  # minLng


def test_no_token_disables_the_layer_without_erroring():
    result = asyncio.run(fetch_mapillary_photos(*BURRUSS, token=""))
    assert result["attempted"] is False
    assert result["photos"] == []
    # The required path is manual upload, and that is what the caller is told.
    assert result["requiresManualUpload"] is True


def test_route_reports_no_coverage_as_200_not_an_error(client, monkeypatch):
    async def _empty(*args, **kwargs):
        return {"attempted": True, "photos": [], "attempts": 3, "requiresManualUpload": True}

    monkeypatch.setattr("app.routers.photo.fetch_mapillary_photos", _empty)

    res = client.get("/api/photo/mapillary", params={"lat": 47.7, "lng": -87.5})

    assert res.status_code == 200
    body = res.json()
    assert body["photos"] == []
    assert body["requiresManualUpload"] is True
    assert "error" not in body


def test_route_validates_coordinates(client):
    assert client.get("/api/photo/mapillary", params={"lat": 999, "lng": 0}).status_code == 422


def test_the_step_03_stub_is_gone(client, monkeypatch):
    async def _empty(*args, **kwargs):
        return {"attempted": False, "photos": [], "attempts": 0, "requiresManualUpload": True}

    monkeypatch.setattr("app.routers.photo.fetch_mapillary_photos", _empty)
    # It used to return 501 pointing at the spec file.
    assert client.get("/api/photo/mapillary", params={"lat": 37.2, "lng": -80.4}).status_code == 200


# --- live ------------------------------------------------------------------


@live
@needs_token
def test_live_returns_real_imagery_near_a_blacksburg_building():
    result = asyncio.run(
        fetch_mapillary_photos(*BURRUSS, token=get_settings().mapillary_access_token)
    )

    assert result["attempted"] is True
    assert result["photos"], "Blacksburg coverage was verified on 2026-09-19"

    nearest = result["photos"][0]
    assert nearest["source"] == "mapillary"
    assert nearest["url"].startswith("https://")
    assert nearest["distanceMeters"] < 150
    # Ranked by true distance from the target.
    assert nearest["distanceMeters"] == min(
        p["distanceMeters"] for p in result["photos"] if p["distanceMeters"] is not None
    )
    # captured_at is epoch milliseconds, not seconds.
    assert nearest["capturedAt"] > 1_000_000_000_000


@live
@needs_token
def test_live_falls_through_silently_where_there_is_no_coverage():
    result = asyncio.run(
        fetch_mapillary_photos(*LAKE_SUPERIOR, token=get_settings().mapillary_access_token)
    )

    assert result["attempted"] is True
    assert result["photos"] == []
    # Empty is the expected common case, not a failure.
    assert "error" not in result
    # And it retried before concluding that, because the index is flaky:
    # five identical queries to a dense area returned 0, 2, 5, 6, 5 images.
    assert result["attempts"] > 1
