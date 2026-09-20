from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import app  # noqa: E402
from app.models import GenerationCreate, Placement, ScoredRotation  # noqa: E402
from app.routers.world import get_trash_path  # noqa: E402
from app.store import get_store  # noqa: E402
from app.store.sqlite_store import SqliteStore  # noqa: E402


def pytest_configure(config):  # noqa: ARG001
    """Point the process-wide store at a throwaway file before anything imports.

    Most tests take the isolated `store` fixture below, but two modules build a
    TestClient at import time without overriding the dependency, so a route
    reached through one of them runs against whatever `get_store()` returns.
    That was survivable when the worst a route could do was insert a row; it is
    not now that `DELETE /api/world` exists — the suite would be one stray
    request away from emptying someone's actual world.

    This has to run in `pytest_configure` rather than a session fixture:
    collection imports the test modules first, and by the time a fixture runs
    the store can already be built and cached against the real path.
    """
    import os
    import tempfile

    from app import config as app_config
    from app import store as app_store

    path = Path(tempfile.mkdtemp(prefix="scorched-tests-")) / "test-session.db"
    os.environ["SN_SQLITE_PATH"] = str(path)
    app_config.get_settings.cache_clear()
    app_store.get_store.cache_clear()


@pytest.fixture
def store(tmp_path) -> SqliteStore:
    """A clean SQLite store per test — same schema/semantics as the Supabase one."""
    return SqliteStore(tmp_path / "test.db")


@pytest.fixture
def trash_path(tmp_path) -> Path:
    """Per-test undo stash. Sharing one would let an undo cross tests."""
    return tmp_path / "trash.json"


@pytest.fixture
def client(store, trash_path):
    from fastapi.testclient import TestClient

    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_trash_path] = lambda: trash_path
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
        placement=Placement(
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
