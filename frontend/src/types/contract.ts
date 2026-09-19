/**
 * Mirror of backend/app/models/contracts.py. Change one, change the other.
 */

export type ConfidenceState = "auto-high" | "auto-low" | "manually-verified";

export type WorldState =
  | "reclaimed"
  | "flooded"
  | "scorched"
  | "buried"
  | "petrified";

/** Step 01 — GET /api/geocode?q= */
export interface GeocodeResult {
  found: boolean;
  address: string | null;
  lat: number | null;
  lng: number | null;
  placeId: number | null;
  /** [south, north, west, east] */
  boundingBox: number[] | null;
  addressDetails: Record<string, unknown> | null;
  attribution: string;
}

/** Step 02 — POST /api/footprint */
export interface FootprintCandidate {
  osmId: number;
  osmType: string;
  tags: Record<string, string>;
  /** GeoJSON order: [lng, lat] */
  geometry: [number, number][];
  centroid: [number, number];
  distanceMeters: number;
  footprintWidthMeters: number;
  footprintDepthMeters: number;
  /** Longest-edge compass bearing, 0-180. Step 08's starting rotation guess. */
  rotationDegrees: number;
  boundingBox: {
    minLng: number;
    minLat: number;
    maxLng: number;
    maxLat: number;
  };
}

export interface FootprintResult {
  confidence: ConfidenceState;
  /** Human-readable explanation of why this was or wasn't auto-selected. */
  reason: string;
  /** Null whenever the match is ambiguous — step 09 must ask the user to choose. */
  selected: FootprintCandidate | null;
  candidates: FootprintCandidate[];
  /** Wider pull for step 08 collision + step 10 propagate. Do not re-fetch. */
  neighbors: FootprintCandidate[];
  queryPoint: [number, number];
  matchRadiusMeters: number;
  neighborRadiusMeters: number;
  cached: boolean;
  source: string;
  attribution: string;
}

/** Steps 05-07 — one provider try, as reported by the generation routes. */
export interface ProviderAttempt {
  provider: string;
  ok: boolean;
  error?: string | null;
  ms?: number | null;
  /** Mesh only: 0 = first try, 1 = the retry. */
  round?: number | null;
  /** Provider was on cooldown (quota) or known to be down. */
  skipped?: boolean | null;
  timeout?: boolean | null;
}

/** Step 05 — POST /api/generate-image (multipart: photo, worldStatePrompt) */
export interface GenerateImageResult {
  /** PNG of the redesigned building: the "after" panel, and the input to generate-mesh. */
  imageUrl: string;
  /** The uploaded photo as stored (EXIF-rotated JPEG): the "before" panel. */
  sourcePhotoUrl: string;
  provider: "gemini" | "kontext";
  model: string;
  width: number;
  height: number;
  attempts: ProviderAttempt[];
  cached: boolean;
  elapsedMs: number;
}

/**
 * Step 07 report. Every mesh is glTF +Y up, facade toward +Z, meters, base-center pivot at y=0.
 * deck.gl: getOrientation [0, yaw, 90]; facade compass bearing = 180 - yaw.
 */
export interface MeshNormalization {
  source: string;
  convention: string;
  upAxis: { from: string; rotated: boolean };
  front: { from: string; yawDegrees: number };
  squareUpYawDegrees: number;
  units: { source: string; method: string; scale: number };
  pivot: "base-center";
  /** width = X (along the facade), depth = Z, height = Y — meters. */
  extentsMeters: { width: number; depth: number; height: number };
  footprint: { widthMeters: number | null; depthMeters: number | null; assumed: boolean };
  removedFragments: number;
  faces: number;
  confidence: ConfidenceState;
  warnings: string[];
}

/** Steps 06+07 — POST /api/generate-mesh. Never fails for provider reasons: falls back to the placeholder. */
export interface GenerateMeshResult {
  meshUrl: string;
  /** Provider output before normalization; null for the placeholder. */
  rawMeshUrl: string | null;
  cutoutUrl: string;
  confidence: ConfidenceState;
  provider: "sf3d" | "triposr" | "triposr-local" | "placeholder";
  fallbackReason: string | null;
  normalization: MeshNormalization;
  warnings: string[];
  attempts: ProviderAttempt[];
  cached: boolean;
  elapsedMs: number;
}

/** Step 08 — one scored candidate from the IoU rotation search. */
export interface ScoredRotation {
  /** Offset from the footprint's principal axis: 0, 90, 180 or 270. */
  offsetDegrees: number;
  /** deck.gl yaw, ready for getOrientation. */
  rotationDegrees: number;
  iou: number;
  intersectionAreaSqM: number;
  scale: number;
  /** Fraction of the footprint's length/width the scaled mesh covers. */
  coverage: [number, number];
}

/**
 * Step 08 — why a placement is or is not trusted.
 *
 * `severity` matters: `low` moves the record to auto-low, `info` is recorded but
 * does not. A signal that fires on every building tells step 09 nothing, and the
 * single-view depth shortfall fires on every real mesh.
 */
export interface PlacementFlag {
  subStep: "footprint" | "rotation" | "scale" | "collision" | "ground" | "mesh";
  code: string;
  message: string;
  severity: "low" | "info";
}

/** Step 08 — placement transform */
export interface PlacementRecord {
  /**
   * deck.gl yaw, fed straight into getOrientation as [0, yaw, 90].
   * Facade compass bearing = 180 - yaw.
   */
  rotationDegrees: number;
  /** Uniform fit factor, and the baseline for the non-uniform fallback. */
  scale: number;
  /** [lat, lng, z] */
  position: [number, number, number];
  confidence: ConfidenceState;
  scoredRotationCandidates: ScoredRotation[];

  /** Everything below is added by step 08 and read by step 09. */
  scaleMode?: "uniform" | "non-uniform";
  /**
   * Per-axis scale in model order (X, Y, Z). Present when the plan had to be
   * stretched to fit the footprint — a mesh from one photograph under-guesses
   * depth, so this is the common case, not the exception.
   */
  scaleXYZ?: [number, number, number];
  scaleStretchRatio?: number;
  flags?: PlacementFlag[];
  collision?: {
    neighborsChecked: number;
    overlaps: {
      neighborId: number | string | null;
      overlapAreaSqM: number;
      overlapRatio: number;
      overlapRatioOfMesh: number;
      overlapRatioOfNeighbor: number;
    }[];
    worstOverlapRatio: number;
  };
  ground?: { meshBaseOffsetUnits: number; z: number };
  diagnostics?: {
    iou: number;
    /** The best IoU any convex mesh outline could score against this polygon. */
    maxAchievableIou: number;
    /** `iou / maxAchievableIou` — what the confidence check actually judges. */
    fitQuality: number;
    footprintAreaSqM: number;
    placedMeshAreaSqM: number;
    footprintPrincipalAxisDegrees: number;
    footprintLengthMeters: number;
    footprintWidthMeters: number;
    meshPrincipalAxisDegrees: number;
    meshWidthUnits: number;
    meshDepthUnits: number;
    meshHeightUnits: number;
    scaledHeightMeters: number;
    upAxis: "y" | "z";
    headingDegrees: number;
    /** How much better the winner scores than its own 180° flip. Near zero. */
    rotationFlipMargin: number | null;
    refinementShiftMeters: number;
    footprintDerivedMismatch:
      | { field: string; reported: number; computed: number }[]
      | null;
  };
}

/**
 * Step 04 — one World State on the Present ↔ Collapsed spectrum.
 *
 * Note what is absent: the prompt text. The five locked strings stay
 * server-side, so the browser has nothing to echo back.
 */
export interface WorldStateOption {
  id: WorldState;
  label: string;
  blurb: string;
  /** 0 = nearest the present, 1 = furthest collapsed. Orders the spectrum. */
  spectrumPosition: number;
}

export interface WorldStateListResponse {
  states: WorldStateOption[];
  order: WorldState[];
  spectrum: { from: string; to: string };
}

/** What the browser sends: an enum, or the user's own words. Never a preset. */
export interface WorldStateSelection {
  worldState: WorldState | null;
  /** When non-empty this REPLACES the preset — it is never appended to it. */
  freeformOverride: string | null;
}

export interface WorldStatePrompt {
  prompt: string;
  source: "preset" | "override";
  worldState: WorldState | null;
}

/** Step 03 path B — a nearby street-level capture. */
export interface MapillaryPhoto {
  source: "mapillary";
  id: string;
  url: string;
  mimeType: string;
  /** Epoch milliseconds, not seconds. */
  capturedAt: number | null;
  location: { lat: number; lng: number } | null;
  distanceMeters: number | null;
}

export interface MapillaryLookup {
  attempted: boolean;
  photos: MapillaryPhoto[];
  attempts: number;
  bbox?: string;
  /** Zero photos is the expected common case, never an error state. */
  requiresManualUpload: boolean;
}

/** Step 11 — one row per generation, never one per address. */
export interface Generation {
  id: string | null;
  address: string;
  lat: number;
  lng: number;
  source_photo: string | null;
  artifact: string | null;
  placement: PlacementRecord | null;
  mesh_url: string | null;
  world_state: WorldState | null;
  confidence_state: ConfidenceState;
  created_at: string | null;
}
