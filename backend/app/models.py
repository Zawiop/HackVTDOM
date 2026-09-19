"""Record shapes for step 11 persistence.

Field names deliberately mirror Procedura / Scorched Nebraska vocabulary
(`artifact`, `placement`, `source_photo`) rather than generic CRUD terms.
Do not rename them.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ConfidenceState = Literal["auto-high", "auto-low", "manually-verified"]
WorldState = Literal["reclaimed", "flooded", "scorched", "buried", "petrified"]

CONFIDENCE_STATES: tuple[str, ...] = ("auto-high", "auto-low", "manually-verified")


class ScoredRotation(BaseModel):
    """One candidate from step 08's IoU rotation search.

    Step 09 replays these as "try these alignments" buttons, so the scores
    must survive the round trip to the database intact.
    """

    model_config = ConfigDict(extra="allow")

    rotationDegrees: float
    iou: float


class Placement(BaseModel):
    """Step 08's transform record, stored verbatim in the `placement` column.

    `extra="allow"` is intentional: step 08 is being built in parallel and may
    add fields. Persistence must never silently drop data it does not recognise.
    """

    model_config = ConfigDict(extra="allow")

    rotationDegrees: float = 0.0
    scale: float = 1.0
    # [lat, lng, z] — z is the ground-alignment offset from step 08.
    position: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    confidence: Literal["auto-high", "auto-low", "manually-verified"] = "auto-low"
    scoredRotationCandidates: list[ScoredRotation] = Field(default_factory=list)

    @field_validator("position")
    @classmethod
    def _position_is_triple(cls, v: list[float]) -> list[float]:
        if len(v) == 2:  # tolerate [lat, lng] and ground it at z=0
            return [v[0], v[1], 0.0]
        if len(v) != 3:
            raise ValueError("placement.position must be [lat, lng, z]")
        return list(v)


class GenerationCreate(BaseModel):
    """Payload accepted by POST /api/generations."""

    model_config = ConfigDict(extra="forbid")

    address: str
    lat: float
    lng: float
    source_photo: str | None = None
    artifact: str | None = None
    placement: Placement = Field(default_factory=Placement)
    mesh_url: str | None = None
    world_state: str | None = None
    confidence_state: ConfidenceState | None = None
    propagated_from: str | None = None

    @field_validator("address")
    @classmethod
    def _address_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("address must not be blank")
        return v

    def resolved_confidence_state(self) -> str:
        """Row-level state defaults to whatever step 08 put in the transform.

        Keeping these two in sync matters: step 12 renders the warning ring off
        `confidence_state`, while step 09's buttons read `placement.confidence`.
        """
        return self.confidence_state or self.placement.confidence


class Correction(BaseModel):
    """Step 09 writes corrected transform values back to an existing row.

    Only transform fields are mutable. The correction always flips the row to
    `manually-verified` — a human closing the loop is recorded as such, never
    laundered into looking like the algorithm got it right the first time.
    """

    model_config = ConfigDict(extra="forbid")

    rotationDegrees: float | None = None
    scale: float | None = None
    position: list[float] | None = None

    @field_validator("position")
    @classmethod
    def _position_is_triple(cls, v: list[float] | None) -> list[float] | None:
        if v is None:
            return None
        if len(v) == 2:
            return [v[0], v[1], 0.0]
        if len(v) != 3:
            raise ValueError("position must be [lat, lng, z]")
        return list(v)

    def is_empty(self) -> bool:
        return self.rotationDegrees is None and self.scale is None and self.position is None


class Generation(BaseModel):
    """A persisted row. One row per generation — never one per address."""

    model_config = ConfigDict(extra="allow")

    id: str
    address: str
    lat: float
    lng: float
    source_photo: str | None = None
    artifact: str | None = None
    placement: dict[str, Any] = Field(default_factory=dict)
    mesh_url: str | None = None
    world_state: str | None = None
    confidence_state: ConfidenceState = "auto-low"
    propagated_from: str | None = None
    created_at: str

    @field_validator("created_at", mode="before")
    @classmethod
    def _iso(cls, v: Any) -> str:
        if isinstance(v, datetime):
            return v.astimezone(timezone.utc).isoformat()
        return str(v)
