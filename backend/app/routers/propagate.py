"""Step 10: extend one building's World State to its neighbours.

Demo-day contract (from 10-propagate.md): clicking Propagate during judging
must be an *instant reveal of already-computed rows*, not a live wait on two
async generation calls per neighbour. So this endpoint reads pre-baked rows out
of the store and never triggers generation itself.

Neighbours that have no pre-baked row yet come back as `pending`, so the UI can
say "3 revealed, 2 not pre-baked" honestly instead of silently showing fewer
buildings than the radius implies.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..geo import VALID_RADII_M, haversine_meters, within_radius
from ..models.contracts import Generation
from ..store import GenerationStore, NotFoundError, PersistenceError, get_store

log = logging.getLogger("scorched.propagate")
router = APIRouter(tags=["propagate"])

# A pre-baked row this close to a supplied footprint centroid is that building.
NEIGHBOUR_MATCH_M = 20.0


class NeighbourFootprint(BaseModel):
    """A neighbour from step 02's cached Overpass response.

    Accepts step 02's `FootprintCandidate` verbatim: that model carries
    `centroid` in GeoJSON [lng, lat] order, so the frontend can hand us
    `footprintResult.neighbors` untouched. Explicit lat/lng still works for
    callers that have plain coordinates.

    Optional either way — propagate works by matching stored rows alone.
    Supplying neighbours is what lets the UI report `pending` ones honestly.
    """

    model_config = ConfigDict(extra="allow")

    lat: float | None = None
    lng: float | None = None
    centroid: list[float] | None = None  # [lng, lat], GeoJSON order
    address: str | None = None
    osmId: int | str | None = None

    @model_validator(mode="after")
    def _resolve_coords(self) -> "NeighbourFootprint":
        if self.lat is None or self.lng is None:
            if self.centroid is None or len(self.centroid) < 2:
                raise ValueError(
                    "neighbour needs either lat+lng or centroid [lng, lat]"
                )
            # GeoJSON is [lng, lat] — getting this backwards is the classic bug.
            self.lng, self.lat = float(self.centroid[0]), float(self.centroid[1])
        return self

    @property
    def label(self) -> str:
        return self.address or (f"osm {self.osmId}" if self.osmId else "unnamed")


class PropagateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_generation_id: str
    radius_meters: int = 100
    neighbors: list[NeighbourFootprint] = Field(default_factory=list)

    @field_validator("radius_meters")
    @classmethod
    def _valid_radius(cls, v: int) -> int:
        if v not in VALID_RADII_M:
            raise ValueError(f"radius_meters must be one of {list(VALID_RADII_M)}")
        return v


class PropagateResponse(BaseModel):
    source: Generation
    radius_meters: int
    world_state: str | None
    revealed: list[Generation]
    pending: list[dict]
    counts: dict


@router.get("/propagate/radii")
def radii() -> dict:
    return {"radii_meters": list(VALID_RADII_M)}


@router.post("/propagate", response_model=PropagateResponse)
def propagate(
    req: PropagateRequest, store: GenerationStore = Depends(get_store)
) -> PropagateResponse:
    try:
        source = store.get_generation(req.source_generation_id)
        all_rows = store.list_generations()
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=e.detail) from e
    except PersistenceError as e:
        log.error("PERSISTENCE FAILURE [%s]: %s", e.operation, e.detail)
        raise HTTPException(
            status_code=502, detail=f"persistence.{e.operation}: {e.detail}"
        ) from e

    origin = (source.lat, source.lng)
    candidates = [r.model_dump() for r in all_rows if r.id != source.id]

    # Same World State only: propagate spreads *this* state, not every row nearby.
    if source.world_state is not None:
        candidates = [c for c in candidates if c.get("world_state") == source.world_state]

    revealed_dicts = within_radius(origin, candidates, req.radius_meters)
    revealed = [Generation(**{k: v for k, v in r.items() if k != "distance_m"})
                for r in revealed_dicts]

    # Neighbours supplied by step 02 that have no pre-baked row within match distance.
    pending: list[dict] = []
    for n in within_radius(origin, [n.model_dump() for n in req.neighbors], req.radius_meters):
        if haversine_meters(source.lat, source.lng, n["lat"], n["lng"]) <= NEIGHBOUR_MATCH_M:
            continue  # this is the source building itself
        matched = any(
            haversine_meters(n["lat"], n["lng"], r.lat, r.lng) <= NEIGHBOUR_MATCH_M
            for r in revealed
        )
        if not matched:
            pending.append(n)

    log.info(
        "propagate %s r=%dm world_state=%s -> revealed=%d pending=%d",
        source.id, req.radius_meters, source.world_state, len(revealed), len(pending),
    )
    return PropagateResponse(
        source=source,
        radius_meters=req.radius_meters,
        world_state=source.world_state,
        revealed=revealed,
        pending=pending,
        counts={
            "revealed": len(revealed),
            "pending": len(pending),
            "pre_baked": len(revealed),
        },
    )
