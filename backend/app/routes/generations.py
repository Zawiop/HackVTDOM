"""Step 11 routes: save a generation, read history, apply a step 09 correction."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from ..models import Correction, Generation, GenerationCreate
from ..store import GenerationStore, NotFoundError, PersistenceError, get_store

log = logging.getLogger("scorched.generations")
router = APIRouter(prefix="/api", tags=["generations"])


def _loud(e: PersistenceError) -> HTTPException:
    """Persistence failures are logged AND returned — never silently swallowed.

    A generation that looks saved in the UI but never reached the database
    would quietly break both history (step 11) and propagate (step 10).
    """
    log.error("PERSISTENCE FAILURE [%s]: %s", e.operation, e.detail)
    return HTTPException(status_code=502, detail=f"persistence.{e.operation}: {e.detail}")


@router.get("/health")
def health(store: GenerationStore = Depends(get_store)) -> dict:
    try:
        return {"ok": True, "store": store.health()}
    except PersistenceError as e:
        raise _loud(e) from e


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
