from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import app  # noqa: E402
from app.models.contracts import GenerationCreate, PlacementRecord, ScoredRotation  # noqa: E402
from app.store import get_store  # noqa: E402
from app.store.sqlite_store import SqliteStore  # noqa: E402


@pytest.fixture
def store(tmp_path) -> SqliteStore:
    """A clean SQLite store per test — same schema/semantics as the Supabase one."""
    return SqliteStore(tmp_path / "test.db")


@pytest.fixture
def client(store):
    from fastapi.testclient import TestClient

    app.dependency_overrides[get_store] = lambda: store
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def sample_payload() -> GenerationCreate:
    """A realistic step-08 output for Burruss Hall, Virginia Tech."""
    return GenerationCreate(
        address="Burruss Hall, Blacksburg, VA",
        lat=37.229_5,
        lng=-80.423_4,
        source_photo="https://example.invalid/burruss-source.jpg",
        artifact="https://example.invalid/burruss-reclaimed.png",
        mesh_url="https://example.invalid/burruss.glb",
        world_state="reclaimed",
        placement=PlacementRecord(
            rotationDegrees=47.5,
            scale=1.83,
            position=[37.229_5, -80.423_4, 0.0],
            confidence="auto-high",
            scoredRotationCandidates=[
                ScoredRotation(rotationDegrees=47.5, iou=0.81),
                ScoredRotation(rotationDegrees=137.5, iou=0.42),
                ScoredRotation(rotationDegrees=227.5, iou=0.79),
                ScoredRotation(rotationDegrees=317.5, iou=0.40),
            ],
        ),
    )
