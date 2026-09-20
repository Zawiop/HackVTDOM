"""Export / import / seed / undo — the persistence safety net (step 11).

The thing these guard is narrow and easy to get wrong: a restored row has to
come back as *the row it was*, with the same id and the same created_at. A
restore that mints new ids silently breaks `propagated_from` links and turns
one undo into a duplicate world.
"""
from __future__ import annotations

import io
import json
import zipfile

import pytest

from app.generation import config as gen_config
from app.models import Generation
from app.services import worldio
from app.store import trash


def _payload(address="Burruss Hall", world_state="scorched", confidence="auto-high"):
    # Import re-points artifact URLs at this host's PUBLIC_BASE_URL (that is what makes a
    # world portable), so build them from the same base or the round-trip compares a
    # rewritten URL against a hardcoded one whenever PUBLIC_BASE_URL isn't the default.
    base = gen_config.PUBLIC_BASE_URL
    return {
        "address": address, "lat": 37.2295, "lng": -80.4234,
        "source_photo": f"{base}/outputs/photos/a.jpg",
        "artifact": f"{base}/outputs/images/b.png",
        "mesh_url": f"{base}/outputs/meshes/c.glb",
        "world_state": world_state,
        "placement": {
            "rotationDegrees": 47.5, "scale": 1.83,
            "position": [37.2295, -80.4234, 0.0], "confidence": confidence,
        },
    }


def test_absolute_local_artifact_is_rebased_onto_the_current_server():
    assert worldio.to_absolute(
        "http://localhost:8000/assets/samples/hitt_flooded.glb",
        "https://deployed.example",
    ) == "https://deployed.example/assets/samples/hitt_flooded.glb"
    assert worldio.to_absolute(
        "http://old-host.test/outputs/meshes/building.glb",
        "https://deployed.example",
    ) == "https://deployed.example/outputs/meshes/building.glb"
    assert worldio.to_absolute(
        "https://external.example/model.glb",
        "https://deployed.example",
    ) == "https://external.example/model.glb"


def _row(**over) -> Generation:
    base = {
        "id": "11111111-1111-1111-1111-111111111111",
        "address": "Burruss Hall", "lat": 37.2295, "lng": -80.4234,
        "source_photo": None, "artifact": None, "mesh_url": None,
        "world_state": "scorched", "confidence_state": "auto-high",
        "propagated_from": None, "created_at": "2026-09-19T12:00:00+00:00",
        "placement": {},
    }
    return Generation(**{**base, **over})


# --- restore keeps identity ----------------------------------------------


def test_restore_preserves_id_and_created_at(store):
    row = _row(id="abc-123", created_at="2020-01-02T03:04:05+00:00")
    assert store.restore_generations([row]) == 1

    back = store.get_generation("abc-123")
    assert back.id == "abc-123"
    # The whole point: a restored row is the row it was, not a copy of it.
    assert back.created_at.startswith("2020-01-02T03:04:05")


def test_restore_is_idempotent(store):
    row = _row(id="dup-1")
    assert store.restore_generations([row]) == 1
    # Second pass adds nothing rather than duplicating or raising — importing
    # the same bundle twice is a thing people do.
    assert store.restore_generations([row]) == 0
    assert len(store.list_generations()) == 1


def test_restore_tops_up_a_partial_world(store):
    store.restore_generations([_row(id="a"), _row(id="b")])
    added = store.restore_generations([_row(id="a"), _row(id="b"), _row(id="c")])
    assert added == 1
    assert {r.id for r in store.list_generations()} == {"a", "b", "c"}


def test_restore_keeps_propagated_from_links_pointing_somewhere(store):
    source = _row(id="src")
    child = _row(id="child", propagated_from="src")
    store.restore_generations([source, child])
    assert store.get_generation("child").propagated_from == "src"


def test_restore_of_nothing_is_not_an_error(store):
    assert store.restore_generations([]) == 0


# --- the undo stash -------------------------------------------------------


def test_stash_peek_take_roundtrip(trash_path):
    rows = [_row(id="x"), _row(id="y")]
    meta = trash.stash(trash_path, rows, action="reset-world", label="two rows")
    assert meta["count"] == 2

    peeked = trash.peek(trash_path)
    assert peeked["action"] == "reset-world"
    # Peek must not consume: the UI reads it to decide whether to offer undo.
    assert trash.peek(trash_path) is not None

    taken, taken_meta = trash.take(trash_path)
    assert [r.id for r in taken] == ["x", "y"]
    assert taken_meta["label"] == "two rows"
    assert trash.peek(trash_path) is None


def test_stash_of_nothing_stashes_nothing(trash_path):
    assert trash.stash(trash_path, [], action="reset-world", label="") is None
    assert trash.peek(trash_path) is None


def test_stash_replaces_rather_than_stacking(trash_path):
    trash.stash(trash_path, [_row(id="old")], action="a", label="old")
    trash.stash(trash_path, [_row(id="new")], action="b", label="new")
    taken, _ = trash.take(trash_path)
    assert [r.id for r in taken] == ["new"]


def test_take_of_an_empty_stash_is_none(trash_path):
    assert trash.take(trash_path) is None


def test_corrupt_stash_is_reported_not_silently_dropped(trash_path):
    trash_path.write_text("{ not json")
    assert trash.peek(trash_path) is None
    assert trash.take(trash_path) is None


def test_stash_over_the_cap_is_refused_loudly(trash_path, monkeypatch):
    monkeypatch.setattr(trash, "MAX_STASHED_ROWS", 2)
    assert trash.stash(trash_path, [_row(id=str(i)) for i in range(3)], action="a", label="") is None


# --- URL rewriting --------------------------------------------------------


@pytest.mark.parametrize("url,expected", [
    ("http://localhost:8000/outputs/meshes/a.glb", "/outputs/meshes/a.glb"),
    ("http://localhost:8000/assets/samples/b.glb", "/assets/samples/b.glb"),
    ("/outputs/meshes/a.glb", "/outputs/meshes/a.glb"),
    # A genuinely external URL is left alone — it is not ours to rewrite.
    ("https://images.example.com/x.png", "https://images.example.com/x.png"),
    (None, None),
])
def test_to_relative(url, expected):
    assert worldio.to_relative(url) == expected


def test_absolutize_uses_the_importing_servers_base():
    rows = worldio.absolutize([_row(mesh_url="/outputs/meshes/a.glb")], base="http://elsewhere:9000")
    assert rows[0].mesh_url == "http://elsewhere:9000/outputs/meshes/a.glb"


def test_absolutize_leaves_external_urls_alone():
    rows = worldio.absolutize([_row(mesh_url="https://cdn.example.com/a.glb")])
    assert rows[0].mesh_url == "https://cdn.example.com/a.glb"


def test_relativize_then_absolutize_is_a_round_trip():
    original = "http://localhost:8000/outputs/meshes/a.glb"
    there = worldio.relativize([_row(mesh_url=original)])
    back = worldio.absolutize(there, base="http://localhost:8000")
    assert back[0].mesh_url == original


# --- bundles --------------------------------------------------------------


def test_bundle_holds_a_manifest_and_reports_missing_files():
    rows = [_row(mesh_url="http://localhost:8000/outputs/meshes/not-there.glb")]
    data, report = worldio.build_bundle(rows)

    z = zipfile.ZipFile(io.BytesIO(data))
    manifest = json.loads(z.read("world.json"))
    assert manifest["count"] == 1
    # A file that is not on disk does not fail the export; it is named, so the
    # person moving the world knows which building will land without a mesh.
    assert report["missing_files"] == ["/outputs/meshes/not-there.glb"]


def test_bundle_does_not_pack_committed_assets():
    """`/assets/...` lives in the repo, so a bundle points at it and moves on."""
    rows = [_row(mesh_url="/assets/samples/burruss_scorched.glb")]
    data, report = worldio.build_bundle(rows)
    assert report["files"] == 0
    assert report["missing_files"] == []
    assert zipfile.ZipFile(io.BytesIO(data)).namelist() == ["world.json"]


def test_read_manifest_accepts_bare_json():
    body, archive = worldio.read_manifest(json.dumps({"generations": []}).encode())
    assert archive is None and body == {"generations": []}


def test_read_manifest_rejects_junk():
    with pytest.raises(worldio.BundleError):
        worldio.read_manifest(b"this is not a bundle")


def test_read_manifest_rejects_a_zip_with_no_manifest():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("something-else.txt", "hi")
    with pytest.raises(worldio.BundleError, match="world.json"):
        worldio.read_manifest(buf.getvalue())


def test_parse_rows_accepts_a_bare_list():
    """A raw `GET /api/generations` dump is what people will paste in."""
    rows = worldio.parse_rows([_row(id="z").model_dump(mode="json")])
    assert [r.id for r in rows] == ["z"]


def test_parse_rows_names_the_row_that_is_wrong():
    with pytest.raises(worldio.BundleError, match="generation 1"):
        worldio.parse_rows([_row().model_dump(mode="json"), {"address": "no id"}])


@pytest.mark.parametrize("name", [
    "files/../../escape.txt",
    "files/outputs/../../../escape.txt",
    "../escape.txt",
    "/etc/passwd",
    "files/etc/passwd",
])
def test_bundle_members_cannot_escape_the_output_directory(name):
    """Zip entries are attacker-controlled the moment a bundle is shared."""
    assert worldio._safe_member_path(name) is None


def test_a_legitimate_member_resolves_under_outputs():
    resolved = worldio._safe_member_path("files/outputs/meshes/ok.glb")
    assert resolved is not None
    assert resolved.name == "ok.glb"


# --- routes ---------------------------------------------------------------


def test_export_json_is_relative_and_portable(client):
    client.post("/api/generations", json=_payload())
    body = client.get("/api/world/export?format=json").json()
    assert body["count"] == 1
    # No absolute host anywhere: that is what lets the bundle land elsewhere.
    assert body["generations"][0]["mesh_url"] == "/outputs/meshes/c.glb"


def test_export_bundle_is_a_zip_with_counts_in_the_headers(client):
    client.post("/api/generations", json=_payload())
    r = client.get("/api/world/export")
    assert r.headers["content-type"] == "application/zip"
    assert r.headers["x-world-rows"] == "1"
    assert "attachment" in r.headers["content-disposition"]
    assert zipfile.ZipFile(io.BytesIO(r.content)).read("world.json")


def test_export_import_round_trips_through_a_bundle(client, store):
    client.post("/api/generations", json=_payload(address="Hitt Hall"))
    original = store.list_generations()[0]
    bundle = client.get("/api/world/export").content

    store.delete_all()
    assert store.list_generations() == []

    r = client.post("/api/world/import", content=bundle)
    assert r.status_code == 200, r.text
    assert r.json()["imported"] == 1

    back = store.list_generations()[0]
    assert back.id == original.id
    assert back.created_at == original.created_at
    assert back.mesh_url == original.mesh_url


def test_import_merge_skips_what_is_already_there(client):
    client.post("/api/generations", json=_payload())
    bundle = client.get("/api/world/export").content
    body = client.post("/api/world/import", content=bundle).json()
    assert (body["imported"], body["skipped_already_present"]) == (0, 1)


def test_import_replace_clears_first_and_leaves_an_undo(client, store):
    client.post("/api/generations", json=_payload(address="Old Hall"))
    bundle = client.get("/api/world/export").content
    store.delete_all()
    client.post("/api/generations", json=_payload(address="New Hall"))

    body = client.post("/api/world/import?mode=replace", content=bundle).json()
    assert body["cleared"] == 1 and body["undoable"] is True
    assert [r.address for r in store.list_generations()] == ["Old Hall"]

    client.post("/api/world/undo")
    assert {r.address for r in store.list_generations()} == {"Old Hall", "New Hall"}


def test_import_rejects_junk_with_a_readable_reason(client):
    r = client.post("/api/world/import", content=b"not a bundle")
    assert r.status_code == 400
    assert "json" in r.json()["detail"].lower()


def test_import_rejects_an_empty_body(client):
    assert client.post("/api/world/import", content=b"").status_code == 400


def test_import_of_a_world_with_no_generations_is_refused(client):
    r = client.post("/api/world/import", content=json.dumps({"generations": []}).encode())
    assert r.status_code == 400


def test_import_rewrites_urls_onto_this_server(client, store):
    payload = {"generations": [_row(id="rel", mesh_url="/outputs/meshes/x.glb").model_dump(mode="json")]}
    client.post("/api/world/import", content=json.dumps(payload).encode())
    assert store.get_generation("rel").mesh_url.startswith("http")


# --- seed -----------------------------------------------------------------


def test_seed_fills_an_empty_world_from_the_repo(client, store):
    body = client.post("/api/world/seed").json()
    assert body["imported"] == body["available"] > 0
    rows = store.list_generations()
    # Everything the seed references must be committed, or a fresh clone
    # renders a world of nothing.
    assert all("/assets/samples/" in (r.mesh_url or "") for r in rows)


def test_seed_twice_does_not_duplicate(client, store):
    first = client.post("/api/world/seed").json()["imported"]
    second = client.post("/api/world/seed").json()
    assert second["imported"] == 0
    assert second["skipped_already_present"] == first
    assert len(store.list_generations()) == first


def test_seeded_meshes_are_actually_on_disk():
    """The seed is only worth having if the files behind it are in the repo."""
    from app.services.worldio import ASSETS_DIR

    for row in worldio.load_seed_world():
        for url in (row.mesh_url, row.artifact, row.source_photo):
            assert url and url.startswith("/assets/")
            assert (ASSETS_DIR / url[len("/assets/"):]).is_file(), url


def test_seed_includes_a_flagged_building_for_the_correction_demo():
    states = {r.confidence_state for r in worldio.load_seed_world()}
    assert "auto-low" in states


# --- undo through the routes ---------------------------------------------


def test_undo_restores_a_reset_world(client, store):
    for name in ("Burruss Hall", "Hitt Hall"):
        client.post("/api/generations", json=_payload(address=name))
    before = {r.id for r in store.list_generations()}

    reset = client.delete("/api/world?confirm=yes").json()
    assert reset == {"removed": 2, "undoable": True}
    assert store.list_generations() == []

    r = client.post("/api/world/undo").json()
    assert r["restored"] == 2 and r["action"] == "reset-world"
    assert {row.id for row in store.list_generations()} == before


def test_undo_restores_a_single_removed_state(client, store):
    created = client.post("/api/generations", json=_payload()).json()
    client.delete(f"/api/generations/{created['id']}")
    assert store.list_generations() == []

    client.post("/api/world/undo")
    assert store.get_generation(created["id"]).world_state == "scorched"


def test_undo_restores_a_whole_removed_building(client, store):
    for state in ("scorched", "flooded", "reclaimed"):
        client.post("/api/generations", json=_payload(world_state=state))
    body = client.delete("/api/generations?address=Burruss Hall").json()
    assert body["removed"] == 3 and body["undoable"] is True

    client.post("/api/world/undo")
    assert len(store.get_history_for_address("Burruss Hall")) == 3


def test_peek_reports_what_undo_would_do(client):
    client.post("/api/generations", json=_payload())
    assert client.get("/api/world/undo").json() == {"available": False}

    client.delete("/api/world?confirm=yes")
    peeked = client.get("/api/world/undo").json()
    assert peeked["available"] is True and peeked["count"] == 1
    # Peeking must not consume the stash.
    assert client.post("/api/world/undo").json()["restored"] == 1


def test_undo_with_nothing_stashed_is_a_404_not_a_quiet_success(client):
    """"Undo did nothing" and "undo restored your world" must not look alike."""
    assert client.post("/api/world/undo").status_code == 404


def test_undo_is_single_level(client, store):
    client.post("/api/generations", json=_payload(address="First"))
    client.delete("/api/world?confirm=yes")
    client.post("/api/generations", json=_payload(address="Second"))
    client.delete("/api/world?confirm=yes")

    client.post("/api/world/undo")
    # Only the most recent batch comes back — see the note in trash.py.
    assert [r.address for r in store.list_generations()] == ["Second"]
    assert client.post("/api/world/undo").status_code == 404


def test_a_failed_delete_id_leaves_no_stash_behind(client):
    assert client.delete("/api/generations/does-not-exist").status_code == 404
    assert client.get("/api/world/undo").json()["available"] is False


# --- one seed source ------------------------------------------------------
#
# `assets/seed-world.json` is the seed dataset: `POST /api/world/seed` loads
# it and `app/startup.py` auto-seeds from it on a cold start. The scripts in
# `seed/` are the tools that produced it and the extras that sit on top.
#
# These guard the boundary between them. It was crossed once: prebake_demo
# wrote Pamplin Hall with its real generated mesh, seed_demo wrote Pamplin
# Hall again with the grey placeholder, both ran at boot, and because the map
# draws the newest row per address the placeholder won — a deployed instance
# served Pamplin as a grey box with its real mesh hidden underneath.


def _seed_addresses() -> set[str]:
    return {r.address for r in worldio.load_seed_world()}


def test_the_seed_world_has_no_duplicate_states():
    rows = worldio.load_seed_world()
    keys = [(r.address, r.world_state) for r in rows]
    assert len(keys) == len(set(keys)), "two rows for the same address and world state"


def test_the_seed_world_has_no_duplicate_ids():
    ids = [r.id for r in worldio.load_seed_world()]
    # Duplicated ids would make restore_generations skip rows as "already
    # present" and silently seed a smaller world than the file describes.
    assert len(ids) == len(set(ids))


def test_seed_demo_does_not_overlap_the_seed_world():
    """The regression this file exists for."""
    from seed import seed_demo

    overlap = seed_demo.addresses() & _seed_addresses()
    assert not overlap, (
        f"seed/seed_demo.py writes {sorted(overlap)}, which the committed seed world "
        "already carries with a real mesh — the placeholder copy would hide it"
    )


def test_prebake_covers_exactly_the_seed_world():
    """The generator and its committed artifact describe the same buildings.

    If they drift, `seed-world.json` is no longer what prebake produces and the
    boot path stops matching what anyone regenerating by hand would get.
    """
    from seed import prebake_demo

    assert {d["address"] for d in prebake_demo.DEMOS} == _seed_addresses()
    baked = {(d["address"], d["world_state"]) for d in prebake_demo.DEMOS}
    seeded = {(r.address, r.world_state) for r in worldio.load_seed_world()}
    assert baked == seeded


def test_every_seed_row_carries_a_real_mesh_not_the_placeholder():
    # The point of the committed seed world is that it shows real generated
    # buildings offline. A placeholder in here would be a grey box on a map
    # whose whole pitch is the buildings.
    for row in worldio.load_seed_world():
        assert row.mesh_url and "placeholder" not in row.mesh_url, row.address


def test_the_boot_path_and_the_seed_route_agree(client, store, monkeypatch):
    """Auto-seed on a cold start == POST /api/world/seed. One dataset, one code path."""
    import asyncio

    from app import startup
    from app import store as store_module

    client.post("/api/world/seed")
    from_route = {(r.id, r.address, r.world_state) for r in store.list_generations()}

    store.delete_all()
    # startup imports build_store inside the function, so it resolves from
    # app.store at call time — patching the startup module would do nothing.
    monkeypatch.setattr(store_module, "build_store", lambda _settings: store)
    asyncio.run(startup.ensure_demo_seeded())
    from_boot = {(r.id, r.address, r.world_state) for r in store.list_generations()}

    assert from_boot == from_route
    assert from_boot, "the boot path seeded nothing"


def test_the_boot_path_leaves_a_populated_store_alone(client, store, monkeypatch):
    import asyncio

    from app import startup
    from app import store as store_module

    client.post("/api/generations", json=_payload(address="Somewhere Real"))
    monkeypatch.setattr(store_module, "build_store", lambda _settings: store)
    asyncio.run(startup.ensure_demo_seeded())

    # A warm instance must not have the demo world appear underneath a real one.
    assert [r.address for r in store.list_generations()] == ["Somewhere Real"]
