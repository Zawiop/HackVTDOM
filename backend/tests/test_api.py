"""HTTP-level contract the frontend (steps 09/10/12) builds against."""
from __future__ import annotations

import pytest


def _payload(address="Burruss Hall", world_state="reclaimed", confidence="auto-high"):
    return {
        "address": address, "lat": 37.2295, "lng": -80.4234,
        "source_photo": "https://example.invalid/a.jpg",
        "artifact": "https://example.invalid/b.png",
        "mesh_url": "https://example.invalid/c.glb",
        "world_state": world_state,
        "placement": {
            "rotationDegrees": 47.5, "scale": 1.83,
            "position": [37.2295, -80.4234, 0.0], "confidence": confidence,
            "scoredRotationCandidates": [
                {"rotationDegrees": 47.5, "iou": 0.81},
                {"rotationDegrees": 227.5, "iou": 0.79},
            ],
        },
    }


def test_health_reports_backend(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["store"]["ok"] is True


def test_post_then_get_roundtrips_over_http(client):
    created = client.post("/api/generations", json=_payload())
    assert created.status_code == 201, created.text
    gid = created.json()["id"]

    fetched = client.get(f"/api/generations/{gid}")
    assert fetched.status_code == 200
    assert fetched.json()["placement"]["scale"] == pytest.approx(1.83)
    assert fetched.json()["mesh_url"] == "https://example.invalid/c.glb"


def test_history_endpoint_returns_sequence(client):
    for ws in ("reclaimed", "flooded"):
        client.post("/api/generations", json=_payload(world_state=ws))
    r = client.get("/api/history", params={"address": "Burruss Hall"})
    assert [g["world_state"] for g in r.json()] == ["reclaimed", "flooded"]


def test_history_requires_an_address(client):
    assert client.get("/api/history").status_code == 422


def test_correction_endpoint_flips_state(client):
    gid = client.post("/api/generations", json=_payload(confidence="auto-low")).json()["id"]
    r = client.patch(f"/api/generations/{gid}/correction", json={"rotationDegrees": 227.5})
    assert r.status_code == 200
    body = r.json()
    assert body["confidence_state"] == "manually-verified"
    assert body["placement"]["rotationDegrees"] == pytest.approx(227.5)


def test_empty_correction_is_rejected(client):
    gid = client.post("/api/generations", json=_payload()).json()["id"]
    assert client.patch(f"/api/generations/{gid}/correction", json={}).status_code == 400


def test_correction_on_missing_row_is_404(client):
    r = client.patch(
        "/api/generations/00000000-0000-0000-0000-000000000000/correction",
        json={"scale": 2.0},
    )
    assert r.status_code == 404


def test_blank_address_rejected(client):
    bad = _payload(address="   ")
    assert client.post("/api/generations", json=bad).status_code == 422


def test_unknown_top_level_field_rejected(client):
    """extra='forbid' catches a teammate sending a field the schema never agreed on."""
    bad = _payload() | {"totally_new_field": 1}
    assert client.post("/api/generations", json=bad).status_code == 422


def test_list_endpoint_feeds_the_map(client):
    client.post("/api/generations", json=_payload(address="A"))
    client.post("/api/generations", json=_payload(address="B"))
    rows = client.get("/api/generations").json()
    assert len(rows) == 2
    assert {"id", "lat", "lng", "placement", "mesh_url", "confidence_state"} <= set(rows[0])


# --- removing buildings ---


def test_delete_one_state_leaves_the_rest(client):
    a = client.post("/api/generations", json=_payload(world_state="reclaimed")).json()
    client.post("/api/generations", json=_payload(world_state="flooded"))

    assert client.delete(f"/api/generations/{a['id']}").status_code == 204

    remaining = client.get("/api/history", params={"address": "Burruss Hall"}).json()
    assert [r["world_state"] for r in remaining] == ["flooded"]


def test_deleting_the_same_row_twice_is_a_404_not_a_silent_success(client):
    gid = client.post("/api/generations", json=_payload()).json()["id"]
    assert client.delete(f"/api/generations/{gid}").status_code == 204
    assert client.delete(f"/api/generations/{gid}").status_code == 404


def test_delete_unknown_row_is_404(client):
    r = client.delete("/api/generations/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404


def test_delete_address_removes_every_state_of_that_building(client):
    for ws in ("reclaimed", "flooded", "scorched"):
        client.post("/api/generations", json=_payload(world_state=ws))
    client.post("/api/generations", json=_payload(address="Norris Hall"))

    r = client.delete("/api/generations", params={"address": "Burruss Hall"})
    assert r.status_code == 200
    assert r.json()["removed"] == 3

    rows = client.get("/api/generations").json()
    assert [row["address"] for row in rows] == ["Norris Hall"]


def test_delete_address_leaves_other_buildings_alone(client):
    client.post("/api/generations", json=_payload(address="Burruss Hall"))
    client.post("/api/generations", json=_payload(address="Norris Hall"))

    client.delete("/api/generations", params={"address": "Burruss Hall"})

    rows = client.get("/api/generations").json()
    assert len(rows) == 1
    assert rows[0]["address"] == "Norris Hall"


def test_delete_address_that_has_nothing_reports_zero(client):
    r = client.delete("/api/generations", params={"address": "Nowhere At All"})
    assert r.status_code == 200
    assert r.json()["removed"] == 0


def test_delete_address_requires_an_address(client):
    assert client.delete("/api/generations").status_code == 422


# --- clearing the whole world ---


def test_reset_world_removes_everything(client):
    for addr in ("Burruss Hall", "Norris Hall"):
        for ws in ("reclaimed", "flooded"):
            client.post("/api/generations", json=_payload(address=addr, world_state=ws))
    assert len(client.get("/api/generations").json()) == 4

    r = client.delete("/api/world", params={"confirm": "yes"})
    assert r.status_code == 200
    assert r.json()["removed"] == 4
    assert client.get("/api/generations").json() == []


def test_reset_world_refuses_without_the_confirmation(client):
    client.post("/api/generations", json=_payload())
    # Nothing sits behind this to undo it, so a bare DELETE must not go through.
    assert client.delete("/api/world").status_code == 422
    assert client.delete("/api/world", params={"confirm": "no"}).status_code == 400
    assert client.delete("/api/world", params={"confirm": "YES"}).status_code == 400
    assert len(client.get("/api/generations").json()) == 1


def test_reset_an_empty_world_is_not_an_error(client):
    r = client.delete("/api/world", params={"confirm": "yes"})
    assert r.status_code == 200
    assert r.json()["removed"] == 0


def test_history_is_empty_after_a_reset(client):
    client.post("/api/generations", json=_payload())
    client.delete("/api/world", params={"confirm": "yes"})
    assert client.get("/api/history", params={"address": "Burruss Hall"}).json() == []


def test_removing_a_buildings_only_state_removes_the_building(client):
    gid = client.post("/api/generations", json=_payload(world_state="scorched")).json()["id"]
    assert client.delete(f"/api/generations/{gid}").status_code == 204
    # Nothing left under that address, so the map has nothing to draw for it.
    assert client.get("/api/history", params={"address": "Burruss Hall"}).json() == []
    assert client.get("/api/generations").json() == []


def test_a_freed_address_can_be_given_a_new_state(client):
    """Remove the scorch, then flood the same building."""
    gid = client.post("/api/generations", json=_payload(world_state="scorched")).json()["id"]
    client.delete(f"/api/generations/{gid}")
    again = client.post("/api/generations", json=_payload(world_state="flooded"))
    assert again.status_code == 201
    states = [r["world_state"] for r in client.get("/api/history", params={"address": "Burruss Hall"}).json()]
    assert states == ["flooded"]
