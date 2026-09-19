"""Shared API contract.

These models are the boundary every other module builds against. `frontend/src/types/contract.ts`
mirrors them field for field — change one, change the other.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

ConfidenceState = Literal["auto-high", "auto-low", "manually-verified"]
WorldState = Literal["reclaimed", "flooded", "scorched", "buried", "petrified"]

CONFIDENCE_STATES: tuple[str, ...] = ("auto-high", "auto-low", "manually-verified")


# --- Step 01: geocode ---


class GeocodeResult(BaseModel):
    found: bool
    address: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    placeId: Optional[int] = None
    # [south, north, west, east] as floats, straight from Nominatim's boundingbox.
    boundingBox: Optional[List[float]] = None
    addressDetails: Optional[Dict[str, Any]] = None
    attribution: str = "© OpenStreetMap contributors"


# --- Step 02: footprint ---


class FootprintRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    radiusMeters: Optional[int] = Field(None, ge=1, le=1000)


class FootprintCandidate(BaseModel):
    osmId: int
    osmType: str
    tags: Dict[str, str] = {}
    # GeoJSON order: [lng, lat]. Kept verbatim for step 08's IoU search.
    geometry: List[List[float]]
    centroid: List[float]
    distanceMeters: float
    footprintWidthMeters: float
    footprintDepthMeters: float
    rotationDegrees: float
    boundingBox: Dict[str, float]


class FootprintResult(BaseModel):
    confidence: ConfidenceState
    reason: str
    # Null whenever the match is ambiguous — step 09 asks the user to choose.
    selected: Optional[FootprintCandidate] = None
    candidates: List[FootprintCandidate] = []
    # Wider pull reused by step 08 collision and step 10 propagate; never re-fetch.
    neighbors: List[FootprintCandidate] = []
    queryPoint: List[float]
    matchRadiusMeters: int
    neighborRadiusMeters: int
    cached: bool = False
    source: str
    attribution: str = "© OpenStreetMap contributors"


# --- Step 08 / 11: placement + persistence ---


class ScoredRotation(BaseModel):
    """One candidate from step 08's IoU rotation search.

    Step 09 replays these as "try these alignments" buttons, so the scores must
    survive the round trip to the database intact.
    """

    model_config = ConfigDict(extra="allow")

    rotationDegrees: float
    iou: float


class PlacementRecord(BaseModel):
    """Step 08's transform record, stored verbatim in the `placement` column.

    `extra="allow"` is deliberate: step 08 may add fields, and persistence must
    never silently drop data it does not recognise.
    """

    model_config = ConfigDict(extra="allow")

    rotationDegrees: float = 0.0
    scale: float = 1.0
    position: List[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])  # [lat, lng, z]
    confidence: ConfidenceState = "auto-low"
    scoredRotationCandidates: List[ScoredRotation] = Field(default_factory=list)

    @field_validator("position")
    @classmethod
    def _position_is_triple(cls, v: List[float]) -> List[float]:
        if len(v) == 2:  # tolerate [lat, lng] and ground it at z=0
            return [v[0], v[1], 0.0]
        if len(v) != 3:
            raise ValueError("placement.position must be [lat, lng, z]")
        return list(v)


class GenerationCreate(BaseModel):
    """Payload accepted by POST /api/generations.

    Unknown top-level fields are rejected so a typo in a field name fails loudly
    instead of silently vanishing.
    """

    model_config = ConfigDict(extra="forbid")

    address: str
    lat: float
    lng: float
    source_photo: Optional[str] = None
    artifact: Optional[str] = None
    placement: PlacementRecord = Field(default_factory=PlacementRecord)
    mesh_url: Optional[str] = None
    world_state: Optional[WorldState] = None
    confidence_state: Optional[ConfidenceState] = None
    propagated_from: Optional[str] = None

    @field_validator("address")
    @classmethod
    def _address_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("address must not be blank")
        return v

    def resolved_confidence_state(self) -> str:
        """Row-level state defaults to whatever step 08 put in the transform.

        Keeping the two in sync matters: step 12 draws the warning ring off
        `confidence_state`, while step 09's buttons read `placement.confidence`.
        """
        return self.confidence_state or self.placement.confidence


class Correction(BaseModel):
    """Step 09 writes corrected transform values back to an existing row.

    Only transform fields are mutable, and a correction always flips the row to
    `manually-verified` — a human closing the loop is recorded as such, never
    laundered into looking like the algorithm got it right first time.
    """

    model_config = ConfigDict(extra="forbid")

    rotationDegrees: Optional[float] = None
    scale: Optional[float] = None
    position: Optional[List[float]] = None

    @field_validator("position")
    @classmethod
    def _position_is_triple(cls, v: Optional[List[float]]) -> Optional[List[float]]:
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
    """A persisted row.

    One row per generation — never one per address. A single address
    accumulates many rows over time, one per World State applied to it.
    """

    model_config = ConfigDict(extra="allow")

    id: str
    address: str
    lat: float
    lng: float
    source_photo: Optional[str] = None
    artifact: Optional[str] = None
    placement: Dict[str, Any] = Field(default_factory=dict)
    mesh_url: Optional[str] = None
    world_state: Optional[WorldState] = None
    confidence_state: ConfidenceState = "auto-low"
    propagated_from: Optional[str] = None
    created_at: str

    @field_validator("created_at", mode="before")
    @classmethod
    def _iso(cls, v: Any) -> str:
        if isinstance(v, datetime):
            return v.astimezone(timezone.utc).isoformat()
        return str(v)
