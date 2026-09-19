"""Shared API contract.

These models are the boundary every other module builds against. `frontend/src/types/contract.ts`
mirrors them field for field — change one, change the other.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

ConfidenceState = str  # 'auto-high' | 'auto-low' | 'manually-verified'
WorldState = str  # 'reclaimed' | 'flooded' | 'scorched' | 'buried' | 'petrified'


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


# --- Step 08 / 11: placement + persistence (owned by teammates) ---


class PlacementRecord(BaseModel):
    rotationDegrees: float
    scale: float
    position: List[float]  # [lat, lng, z]
    confidence: ConfidenceState
    scoredRotationCandidates: List[Dict[str, float]] = []


class Generation(BaseModel):
    id: Optional[str] = None
    address: str
    lat: float
    lng: float
    source_photo: Optional[str] = None
    artifact: Optional[str] = None
    placement: Optional[PlacementRecord] = None
    mesh_url: Optional[str] = None
    world_state: Optional[WorldState] = None
    confidence_state: ConfidenceState = "auto-low"
    created_at: Optional[str] = None
