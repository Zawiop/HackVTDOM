"""Step 10: Propagate reveals pre-baked rows instantly; it never generates live."""
from __future__ import annotations

from app.geo import offset_meters
from app.models.contracts import GenerationCreate, PlacementRecord

ORIGIN = (37.2295, -80.4234)


def _at(store, north_m, east_m, world_state="reclaimed", address=None):
    lat, lng = offset_meters(*ORIGIN, north_m, east_m)
    return store.save_generation(
        GenerationCreate(
            address=address or f"Neighbour {north_m}N {east_m}E",
            lat=lat, lng=lng, world_state=world_state,
            placement=PlacementRecord(confidence="auto-high"),
        )
    )


def _source(store):
    return store.save_generation(
        GenerationCreate(
            address="Burruss Hall", lat=ORIGIN[0], lng=ORIGIN[1],
            world_state="reclaimed", placement=PlacementRecord(confidence="auto-high"),
        )
    )


def test_radius_filters_neighbours(client, store):
    src = _source(store)
    _at(store, 40, 0)     # inside 50
    _at(store, 90, 0)     # inside 100
    _at(store, 200, 0)    # inside 250
    _at(store, 500, 0)    # outside everything

    for radius, expected in ((50, 1), (100, 2), (250, 3)):
        r = client.post("/api/propagate", json={
            "source_generation_id": src.id, "radius_meters": radius,
        })
        assert r.status_code == 200, r.text
        assert r.json()["counts"]["revealed"] == expected, f"radius {radius}"


def test_source_is_excluded_from_its_own_reveal(client, store):
    src = _source(store)
    _at(store, 40, 0)
    r = client.post("/api/propagate", json={
        "source_generation_id": src.id, "radius_meters": 250,
    })
    assert src.id not in [g["id"] for g in r.json()["revealed"]]


def test_only_matching_world_state_is_revealed(client, store):
    src = _source(store)
    _at(store, 40, 0, world_state="reclaimed")
    _at(store, 45, 0, world_state="flooded")
    r = client.post("/api/propagate", json={
        "source_generation_id": src.id, "radius_meters": 250,
    })
    body = r.json()
    assert body["counts"]["revealed"] == 1
    assert body["revealed"][0]["world_state"] == "reclaimed"


def test_unbaked_neighbours_come_back_as_pending(client, store):
    """Honest reporting: a neighbour with no pre-baked row is not silently dropped."""
    src = _source(store)
    _at(store, 40, 0)
    baked_lat, baked_lng = offset_meters(*ORIGIN, 40, 0)
    un_lat, un_lng = offset_meters(*ORIGIN, 120, 0)

    r = client.post("/api/propagate", json={
        "source_generation_id": src.id,
        "radius_meters": 250,
        "neighbors": [
            {"lat": baked_lat, "lng": baked_lng, "address": "already baked"},
            {"lat": un_lat, "lng": un_lng, "address": "not yet generated"},
        ],
    })
    body = r.json()
    assert body["counts"]["revealed"] == 1
    assert body["counts"]["pending"] == 1
    assert body["pending"][0]["address"] == "not yet generated"


def test_invalid_radius_is_rejected(client, store):
    src = _source(store)
    r = client.post("/api/propagate", json={
        "source_generation_id": src.id, "radius_meters": 75,
    })
    assert r.status_code == 422


def test_unknown_source_is_404(client):
    r = client.post("/api/propagate", json={
        "source_generation_id": "00000000-0000-0000-0000-000000000000",
        "radius_meters": 100,
    })
    assert r.status_code == 404
