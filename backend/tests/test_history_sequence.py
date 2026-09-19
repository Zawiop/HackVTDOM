"""Step 11's one hard rule: one row per generation, never one per address."""
from __future__ import annotations

from app.models import GenerationCreate, Placement


def _gen(address: str, world_state: str) -> GenerationCreate:
    return GenerationCreate(
        address=address, lat=37.2295, lng=-80.4234, world_state=world_state,
        placement=Placement(confidence="auto-high"),
    )


def test_same_address_accumulates_rows_never_upserts(store):
    a = "Burruss Hall, Blacksburg, VA"
    first = store.save_generation(_gen(a, "reclaimed"))
    second = store.save_generation(_gen(a, "flooded"))
    third = store.save_generation(_gen(a, "scorched"))

    assert len({first.id, second.id, third.id}) == 3, "each generation needs its own row"
    assert len(store.get_history_for_address(a)) == 3


def test_history_is_ordered_oldest_first(store):
    a = "Torgersen Hall, Blacksburg, VA"
    for ws in ("reclaimed", "flooded", "petrified"):
        store.save_generation(_gen(a, ws))

    seq = [g.world_state for g in store.get_history_for_address(a)]
    assert seq == ["reclaimed", "flooded", "petrified"], "timeline must read Reality -> ..."


def test_history_is_scoped_to_one_address(store):
    store.save_generation(_gen("Building A", "reclaimed"))
    store.save_generation(_gen("Building A", "flooded"))
    store.save_generation(_gen("Building B", "scorched"))

    assert len(store.get_history_for_address("Building A")) == 2
    assert len(store.get_history_for_address("Building B")) == 1
    assert store.get_history_for_address("Nowhere") == []


def test_list_generations_returns_every_row(store):
    store.save_generation(_gen("Building A", "reclaimed"))
    store.save_generation(_gen("Building A", "flooded"))
    store.save_generation(_gen("Building B", "scorched"))
    assert len(store.list_generations()) == 3
