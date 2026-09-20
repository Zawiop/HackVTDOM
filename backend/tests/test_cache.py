"""The footprint cache survives a restart — that is the whole point of it."""

import importlib

import pytest

from app.services import cache as cache_module


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("FOOTPRINT_CACHE_PATH", str(tmp_path / "footprints.json"))
    module = importlib.reload(cache_module)
    yield module
    importlib.reload(cache_module)


def _reopen(cache, tmp_path, monkeypatch):
    """Simulate a server restart against the same cache file."""
    monkeypatch.setenv("FOOTPRINT_CACHE_PATH", str(tmp_path / "footprints.json"))
    return importlib.reload(cache)


ELEMENTS = [{"type": "way", "id": 1, "geometry": [{"lat": 37.2, "lon": -80.4}]}]


def test_round_trips_through_memory(cache):
    cache.put(37.22906, -80.42372, 250, (ELEMENTS, "https://overpass-api.de"))
    assert cache.get(37.22906, -80.42372, 250) == (ELEMENTS, "https://overpass-api.de")


def test_survives_a_restart(cache, tmp_path, monkeypatch):
    cache.put(37.22906, -80.42372, 250, (ELEMENTS, "https://overpass-api.de"))

    restarted = _reopen(cache, tmp_path, monkeypatch)
    assert restarted.size() == 1
    assert restarted.get(37.22906, -80.42372, 250)[0] == ELEMENTS


def test_coordinate_jitter_inside_a_building_still_hits(cache):
    cache.put(37.22906, -80.42372, 250, (ELEMENTS, "src"))
    # ~5 m away: rounds to the same 4-decimal key.
    assert cache.get(37.229061, -80.423718, 250) is not None


def test_a_different_radius_is_a_different_entry(cache):
    cache.put(37.22906, -80.42372, 250, (ELEMENTS, "src"))
    assert cache.get(37.22906, -80.42372, 50) is None


def test_clear_is_not_undone_by_a_later_lazy_load(cache, tmp_path, monkeypatch):
    cache.put(37.22906, -80.42372, 250, (ELEMENTS, "src"))
    cache.clear()
    assert cache.size() == 0

    restarted = _reopen(cache, tmp_path, monkeypatch)
    assert restarted.size() == 0


def test_a_corrupt_cache_file_does_not_take_the_api_down(cache, tmp_path, monkeypatch):
    (tmp_path / "footprints.json").write_text("{ this is not json")

    restarted = _reopen(cache, tmp_path, monkeypatch)
    assert restarted.size() == 0
    restarted.put(37.0, -80.0, 250, (ELEMENTS, "src"))
    assert restarted.get(37.0, -80.0, 250) is not None
