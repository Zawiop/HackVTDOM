"""Step 11 routes: save a generation, read history, apply a step 09 correction."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from ..models import Correction, Generation, GenerationCreate
from ..security import require_admin
from ..store import GenerationStore, NotFoundError, PersistenceError, get_store, trash
from .world import get_trash_path

log = logging.getLogger("scorched.generations")
router = APIRouter(prefix="/api", tags=["generations"])


def _loud(e: PersistenceError) -> HTTPException:
    """Persistence failures are logged AND returned — never silently swallowed.

    A generation that looks saved in the UI but never reached the database
    would quietly break both history (step 11) and propagate (step 10).
    """
    log.error("PERSISTENCE FAILURE [%s]: %s", e.operation, e.detail)
    return HTTPException(status_code=502, detail=f"persistence.{e.operation}: {e.detail}")


@router.post("/generations", response_model=Generation, status_code=201)
def create_generation(
    payload: GenerationCreate, store: GenerationStore = Depends(get_store)
) -> Generation:
    """Insert one row. Never an upsert — a repeat address appends to its history."""
    try:
        row = store.save_generation(payload)
    except PersistenceError as e:
        raise _loud(e) from e
    log.info("saved generation %s for %r (%s)", row.id, row.address, row.confidence_state)
    return row


@router.get("/generations", response_model=list[Generation])
def list_generations(store: GenerationStore = Depends(get_store)) -> list[Generation]:
    """Every row, for the step 12 ScenegraphLayer."""
    try:
        return store.list_generations()
    except PersistenceError as e:
        raise _loud(e) from e


@router.get("/generations/{generation_id}", response_model=Generation)
def get_generation(
    generation_id: str, store: GenerationStore = Depends(get_store)
) -> Generation:
    try:
        return store.get_generation(generation_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=e.detail) from e
    except PersistenceError as e:
        raise _loud(e) from e


@router.get("/history", response_model=list[Generation])
def get_history(
    address: str = Query(..., min_length=1),
    store: GenerationStore = Depends(get_store),
) -> list[Generation]:
    """The sequence for one address, oldest first: Reality -> Flooded -> Reclaimed."""
    try:
        return store.get_history_for_address(address.strip())
    except PersistenceError as e:
        raise _loud(e) from e


@router.patch("/generations/{generation_id}/correction", response_model=Generation)
def correct_generation(
    generation_id: str,
    correction: Correction,
    store: GenerationStore = Depends(get_store),
) -> Generation:
    """Step 09: persist a human's corrected transform, flip to manually-verified."""
    if correction.is_empty():
        raise HTTPException(
            status_code=400,
            detail="correction must change at least one of rotationDegrees, scale, position",
        )
    try:
        row = store.apply_correction(generation_id, correction)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=e.detail) from e
    except PersistenceError as e:
        raise _loud(e) from e
    log.info("correction applied to %s -> manually-verified", generation_id)
    return row


@router.delete("/generations/{generation_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_generation(
    generation_id: str,
    store: GenerationStore = Depends(get_store),
    trash_path: Path = Depends(get_trash_path),
) -> Response:
    """Remove one generation.

    Deliberately per-row rather than per-address: a building usually has
    several World States and the common case is dropping one of them, not
    wiping the building. Use the address form below to clear it entirely.

    The row is stashed before it goes, so POST /api/world/undo can put it back.
    """
    try:
        # Read it first — both to 404 on a bad id and to have something to
        # stash. Deleting and then discovering there is nothing to undo is the
        # wrong order.
        row = store.get_generation(generation_id)
        trash.stash(
            trash_path, [row],
            action="delete-generation",
            label=f"{row.address} — {row.world_state or 'no world state'}",
        )
        store.delete_generation(generation_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=e.detail) from e
    except PersistenceError as e:
        raise _loud(e) from e
    log.info("deleted generation %s", generation_id)
    return Response(status_code=204)


@router.delete("/generations", status_code=200, dependencies=[Depends(require_admin)])
def delete_address(
    address: str = Query(..., min_length=1),
    store: GenerationStore = Depends(get_store),
    trash_path: Path = Depends(get_trash_path),
) -> dict:
    """Remove every generation for an address — clears the building off the map.

    Stashed first, so POST /api/world/undo restores the whole building.
    """
    address = address.strip()
    try:
        doomed = store.get_history_for_address(address)
        stashed = trash.stash(
            trash_path, doomed,
            action="delete-address",
            label=f"{address} — all {len(doomed)} state(s)",
        )
        removed = store.delete_by_address(address)
    except PersistenceError as e:
        raise _loud(e) from e
    log.info("deleted %d generation(s) for %r", removed, address)
    return {"address": address, "removed": removed, "undoable": stashed is not None}


@router.delete("/world", status_code=200, dependencies=[Depends(require_admin)])
def reset_world(
    confirm: str = Query(..., description="must be the literal string 'yes'"),
    store: GenerationStore = Depends(get_store),
    trash_path: Path = Depends(get_trash_path),
) -> dict:
    """Empty the world — every building, every World State.

    Requires `confirm=yes` in the query string, so a bare DELETE on this path
    is refused rather than trusted.

    The whole world is stashed before it goes: POST /api/world/undo puts it
    back verbatim, with no regeneration. `undoable: false` in the response
    means the stash could not be written and the reset is final — check it
    rather than assuming the net is there.
    """
    if confirm != "yes":
        raise HTTPException(status_code=400, detail="pass confirm=yes to reset the world")
    try:
        doomed = store.list_generations()
        stashed = trash.stash(
            trash_path, doomed,
            action="reset-world",
            label=f"the whole world — {len(doomed)} generation(s)",
        )
        removed = store.delete_all()
    except PersistenceError as e:
        raise _loud(e) from e
    log.warning("world reset: removed %d generation(s)", removed)
    return {"removed": removed, "undoable": stashed is not None}
