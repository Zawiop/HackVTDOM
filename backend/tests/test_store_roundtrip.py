"""Requirement: a save must actually round-trip — write it, read it back, compare."""
from __future__ import annotations

import pytest

from app.models.contracts import Correction, GenerationCreate, PlacementRecord
from app.store.errors import NotFoundError, PersistenceError


def test_save_roundtrips_every_field(store, sample_payload):
    saved = store.save_generation(sample_payload)
    read_back = store.get_generation(saved.id)

    assert read_back.id == saved.id
    assert read_back.address == sample_payload.address
    assert read_back.lat == pytest.approx(sample_payload.lat)
    assert read_back.lng == pytest.approx(sample_payload.lng)
    assert read_back.source_photo == sample_payload.source_photo
    assert read_back.artifact == sample_payload.artifact
    assert read_back.mesh_url == sample_payload.mesh_url
    assert read_back.world_state == sample_payload.world_state
    assert read_back.created_at


def test_placement_json_survives_intact(store, sample_payload):
    """Step 09 replays scoredRotationCandidates — they must not be flattened."""
    saved = store.save_generation(sample_payload)
    p = store.get_generation(saved.id).placement

    assert p["rotationDegrees"] == pytest.approx(47.5)
    assert p["scale"] == pytest.approx(1.83)
    assert p["position"] == [37.2295, -80.4234, 0.0]
    assert len(p["scoredRotationCandidates"]) == 4
    assert p["scoredRotationCandidates"][0]["iou"] == pytest.approx(0.81)


def test_confidence_state_defaults_from_placement(store):
    low = GenerationCreate(
        address="Torgersen Hall", lat=37.2296, lng=-80.4139,
        placement=PlacementRecord(confidence="auto-low"),
    )
    assert store.save_generation(low).confidence_state == "auto-low"


def test_unknown_placement_fields_are_preserved(store):
    """Step 08 is being built in parallel; persistence must not drop new fields."""
    payload = GenerationCreate(
        address="Unknown-Fields Hall", lat=37.0, lng=-80.0,
        placement=PlacementRecord.model_validate(
            {"rotationDegrees": 10.0, "scale": 1.0, "footprintIoU": 0.93,
             "collisionFlag": False, "confidence": "auto-high"}
        ),
    )
    p = store.get_generation(store.save_generation(payload).id).placement
    assert p["footprintIoU"] == pytest.approx(0.93)
    assert p["collisionFlag"] is False


def test_missing_row_raises_loudly(store):
    with pytest.raises(NotFoundError):
        store.get_generation("00000000-0000-0000-0000-000000000000")


def test_write_failure_raises_not_silently_swallowed(tmp_path, sample_payload):
    """A broken store must raise — never let the UI think a save worked."""
    from app.store.sqlite_store import SqliteStore

    s = SqliteStore(tmp_path / "broken.db")
    s.path = tmp_path / "nonexistent-dir" / "x" / "broken.db"  # force a failure
    s.path.parent.mkdir(parents=True, exist_ok=True)
    s.path.parent.chmod(0o500)  # read-only dir
    try:
        with pytest.raises(PersistenceError):
            s.save_generation(sample_payload)
    finally:
        s.path.parent.chmod(0o700)
