"""Shared API contract.

These models are the boundary every other module builds against. `frontend/src/types/contract.ts`
mirrors them field for field — change one, change the other.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

ConfidenceState = Literal["auto-high", "auto-low", "manually-verified"]
WorldState = Literal["reclaimed", "flooded", "scorched", "buried", "petrified"]

CONFIDENCE_STATES: tuple = ("auto-high", "auto-low", "manually-verified")


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


# --- Steps 05-07: image edit, mesh generation, mesh normalization ---


class ProviderAttempt(BaseModel):
    provider: str
    ok: bool
    error: Optional[str] = None
    ms: Optional[int] = None
    round: Optional[int] = None  # mesh only: 0 = first try, 1 = the retry
    skipped: Optional[bool] = None  # provider was on cooldown (quota) or known-down
    timeout: Optional[bool] = None


class GenerateImageResult(BaseModel):
    # PNG of the redesigned building: the "after" panel and the input to /generate-mesh.
    imageUrl: str
    # The uploaded photo as the backend stored it (EXIF-rotated JPEG): the "before" panel.
    sourcePhotoUrl: str
    provider: str  # 'gemini' | 'kontext'
    model: str
    width: int
    height: int
    attempts: List[ProviderAttempt]
    cached: bool
    elapsedMs: int


class MeshNormalization(BaseModel):
    source: str
    # Always "glTF +Y up; facade faces +Z; meters; origin at base-center (y=0 is ground)".
    # With deck.gl ScenegraphLayer getOrientation [0, yaw, 90]: upright, facade faces south at
    # yaw 0, facade compass bearing = 180 - yaw.
    convention: str
    upAxis: Dict[str, Any]
    front: Dict[str, Any]
    squareUpYawDegrees: float
    units: Dict[str, Any]
    pivot: str
    # Meters after normalization. width = X (along the facade), depth = Z, height = Y.
    extentsMeters: Dict[str, float]
    footprint: Dict[str, Any]
    removedFragments: int
    faces: int
    confidence: ConfidenceState
    warnings: List[str]


class GenerateMeshResult(BaseModel):
    # Normalized .glb, ready for step 08: meters, Y-up, base-center pivot, sized to the footprint.
    meshUrl: str
    rawMeshUrl: Optional[str] = None  # provider output before step 07; null for the placeholder
    cutoutUrl: str  # background-removed image actually sent to the mesh model
    confidence: ConfidenceState  # 'auto-high' | 'auto-low'
    provider: str  # 'sf3d' | 'triposr' | 'triposr-local' | 'placeholder'
    fallbackReason: Optional[str] = None
    normalization: MeshNormalization
    warnings: List[str]
    attempts: List[ProviderAttempt]
    cached: bool
    elapsedMs: int


class NormalizeMeshResult(BaseModel):
    meshUrl: str
    confidence: ConfidenceState
    normalization: MeshNormalization


# --- Step 08: placement transform ---


class MeshExtents(BaseModel):
    """Step 07's `normalization.extentsMeters`. Metres, after normalization."""

    width: float = Field(..., gt=0)  # X, along the facade
    depth: float = Field(..., gt=0)  # Z
    height: Optional[float] = Field(default=None, gt=0)  # Y


class PlacementRequest(BaseModel):
    """Everything step 08 needs, all of it already computed by steps 02 and 07."""

    footprint: "FootprintCandidate"
    meshExtentsMeters: MeshExtents
    # Reused from the step 02 response — step 08 must not re-query Overpass.
    neighbors: List["FootprintCandidate"] = []
    # Carried through so an ambiguous match in step 02 cannot be laundered into
    # a confident placement here.
    footprintConfidence: ConfidenceState = "auto-high"


class ScoredRotationCandidate(BaseModel):
    rotationDegrees: float
    offsetDegrees: float
    iou: float
    scale: float


class PlacementCheck(BaseModel):
    ok: bool
    detail: str


class PlacementResult(BaseModel):
    rotationDegrees: float
    scale: float
    # Present only when proportions disagree enough that uniform scaling looks
    # undersized. Step 12 renders `scale`; read this when it is not null.
    scaleXYZ: Optional[List[float]] = None
    position: List[float]  # [lat, lng, z]
    confidence: ConfidenceState
    # Kept whole so step 09 can offer them as "try these alignments" buttons.
    scoredRotationCandidates: List[ScoredRotationCandidate]
    # Per-check so step 09 knows which uncertainty it is showing.
    checks: Dict[str, PlacementCheck]
    # Footprint area as a share of its oriented bounding box. Caps how high a
    # rectangular mesh footprint can score, so the rotation test is judged against it.
    rectangularity: float
    warnings: List[str] = []
    rotation_note: str = ""


# --- Step 08 / 11: placement + persistence ---
#
# Field names deliberately mirror Procedura / Scorched Nebraska vocabulary
# (`artifact`, `placement`, `source_photo`) rather than generic CRUD terms.
# Do not rename them.


class ScoredRotation(BaseModel):
    """One candidate from step 08's IoU rotation search.

    Step 09 replays these as "try these alignments" buttons, so the scores must
    survive the round trip to the database intact.
    """

    model_config = ConfigDict(extra="allow")

    rotationDegrees: float
    iou: float


class Placement(BaseModel):
    """Step 08's transform record, stored verbatim in the `placement` column.

    `extra="allow"` is intentional: step 08 is still being built and may add
    fields. Persistence must never silently drop data it does not recognise.
    """

    model_config = ConfigDict(extra="allow")

    rotationDegrees: float = 0.0
    scale: float = 1.0
    # [lat, lng, z] — z is the ground-alignment offset from step 08.
    position: List[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
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
    """Payload accepted by POST /api/generations."""

    model_config = ConfigDict(extra="forbid")

    address: str
    lat: float
    lng: float
    source_photo: Optional[str] = None
    artifact: Optional[str] = None
    placement: Placement = Field(default_factory=Placement)
    mesh_url: Optional[str] = None
    world_state: Optional[str] = None
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
    """A persisted row. One row per generation — never one per address."""

    model_config = ConfigDict(extra="allow")

    id: str
    address: str
    lat: float
    lng: float
    source_photo: Optional[str] = None
    artifact: Optional[str] = None
    placement: Dict[str, Any] = Field(default_factory=dict)
    mesh_url: Optional[str] = None
    world_state: Optional[str] = None
    confidence_state: ConfidenceState = "auto-low"
    propagated_from: Optional[str] = None
    created_at: str

    @field_validator("created_at", mode="before")
    @classmethod
    def _iso(cls, v: Any) -> str:
        if isinstance(v, datetime):
            return v.astimezone(timezone.utc).isoformat()
        return str(v)
