"""Destructive endpoints are open when ADMIN_TOKEN is unset (local dev), and
enforced once it is set — this is what stands between a public URL and anyone
with curl wiping the demo via DELETE /world, which /docs documents by name.
"""

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app

client = TestClient(app)


def _seed_one_row() -> str:
    body = {
        "address": "Auth Test Hall, Blacksburg, VA",
        "lat": 37.0,
        "lng": -80.0,
        "placement": {"rotationDegrees": 0.0, "scale": 1.0, "confidence": "auto-high"},
    }
    return client.post("/api/generations", json=body).json()["id"]


def test_open_when_admin_token_is_unset(monkeypatch):
    monkeypatch.setattr(get_settings(), "admin_token", "")
    row_id = _seed_one_row()

    response = client.delete(f"/api/generations/{row_id}")
    assert response.status_code == 204


def test_rejects_missing_header_when_admin_token_is_set(monkeypatch):
    monkeypatch.setattr(get_settings(), "admin_token", "secret123")
    row_id = _seed_one_row()

    response = client.delete(f"/api/generations/{row_id}")
    assert response.status_code == 401


def test_rejects_wrong_token(monkeypatch):
    monkeypatch.setattr(get_settings(), "admin_token", "secret123")
    row_id = _seed_one_row()

    response = client.delete(
        f"/api/generations/{row_id}", headers={"X-Admin-Token": "wrong"}
    )
    assert response.status_code == 401


def test_accepts_correct_token(monkeypatch):
    monkeypatch.setattr(get_settings(), "admin_token", "secret123")
    row_id = _seed_one_row()

    response = client.delete(
        f"/api/generations/{row_id}", headers={"X-Admin-Token": "secret123"}
    )
    assert response.status_code == 204


def test_world_reset_is_gated_too(monkeypatch):
    monkeypatch.setattr(get_settings(), "admin_token", "secret123")
    _seed_one_row()

    denied = client.delete("/api/world?confirm=yes")
    assert denied.status_code == 401

    allowed = client.delete(
        "/api/world?confirm=yes", headers={"X-Admin-Token": "secret123"}
    )
    assert allowed.status_code == 200


def test_delete_by_address_is_gated_too(monkeypatch):
    monkeypatch.setattr(get_settings(), "admin_token", "secret123")
    _seed_one_row()

    denied = client.delete(
        "/api/generations?address=" + "Auth Test Hall, Blacksburg, VA"
    )
    assert denied.status_code == 401
