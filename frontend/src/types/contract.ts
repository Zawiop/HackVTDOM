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

/** Step 04 — GET /api/worldstates. One point on the Present ↔ Collapsed spectrum.
 *
 * Carries no prompt text on purpose: the five locked descriptions stay server-side
 * so output is consistent whichever building or user triggers them. Send the `id`
 * to /api/generate-image, never a prompt string.
 */
export interface WorldStateOption {
  id: WorldState;
  label: string;
  blurb: string;
  spectrumPosition: number;
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
  /** Step 04: which spectrum point this was. Persisted as `world_state`. */
  worldState: WorldState | null;
  /** `preset:<id>` when the locked description was used, `override` when the user typed one. */
  promptSource: string;
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

/** Step 08 — POST /api/placement */
export interface PlacementRequest {
  footprint: FootprintCandidate;
  meshExtentsMeters: { width: number; depth: number; height?: number };
  /** Reused from the step 02 response — step 08 must not re-query Overpass. */
  neighbors?: FootprintCandidate[];
  footprintConfidence?: ConfidenceState;
}

export interface ScoredRotationCandidate {
  rotationDegrees: number;
  offsetDegrees: number;
  iou: number;
  scale: number;
}

export interface PlacementCheck {
  ok: boolean;
  detail: string;
}

export interface PlacementResult {
  rotationDegrees: number;
  scale: number;
  /** Only set when proportions disagree enough that uniform scale looks undersized. */
  scaleXYZ: [number, number, number] | null;
  /** [lat, lng, z] */
  position: [number, number, number];
  confidence: ConfidenceState;
  /** Step 09 replays these as "try these alignments" buttons. */
  scoredRotationCandidates: ScoredRotationCandidate[];
  /** Keyed by check name, so step 09 knows which uncertainty it is showing. */
  checks: Record<string, PlacementCheck>;
  /** Footprint area as a share of its oriented bounding box. */
  rectangularity: number;
  /** Best IoU this mesh could reach at any rotation, capped by footprint shape
   *  AND mesh area. The rotation check is scored against this, not against 1.0. */
  achievableIou: number;
  warnings: string[];
  rotation_note: string;
}

/** Step 08 — the transform as persisted on a generation row. */
export interface PlacementRecord {
  rotationDegrees: number;
  scale: number;
  /** Non-uniform fit, present only when proportions disagree past 30%. */
  scaleXYZ?: [number, number, number] | null;
  /** [lat, lng, z] */
  position: [number, number, number];
  confidence: ConfidenceState;
  scoredRotationCandidates: { rotationDegrees: number; iou: number }[];
}

/** Step 11 — one row per generation, never one per address.
 *
 * `id` and `created_at` are non-null: every row the store returns has both.
 * The pre-persistence shape is `GenerationCreate` below.
 */
export interface Generation {
  id: string;
  address: string;
  lat: number;
  lng: number;
  source_photo: string | null;
  artifact: string | null;
  placement: PlacementRecord;
  mesh_url: string | null;
  world_state: WorldState | null;
  confidence_state: ConfidenceState;
  /** Set when this row came from a step 10 propagate run. */
  propagated_from?: string | null;
  created_at: string;
}

/** Step 11 — POST /api/generations. Unknown top-level fields are rejected. */
export interface GenerationCreate {
  address: string;
  lat: number;
  lng: number;
  source_photo?: string | null;
  artifact?: string | null;
  placement?: Partial<PlacementRecord>;
  mesh_url?: string | null;
  world_state?: WorldState | null;
  confidence_state?: ConfidenceState | null;
  propagated_from?: string | null;
}

/** Step 09 — PATCH /api/generations/{id}/correction.
 *
 * Only transform fields are mutable. The backend always flips the row to
 * `manually-verified`; the client never sends that itself.
 */
export interface Correction {
  rotationDegrees?: number;
  scale?: number;
  position?: [number, number, number];
}

/** Step 10 — POST /api/propagate. */
export interface PropagateResponse {
  source: Generation;
  radius_meters: number;
  world_state: WorldState | null;
  /** Pre-baked rows inside the radius sharing the source's World State. */
  revealed: Generation[];
  /** Neighbours inside the radius with no generated row yet. */
  pending: { lat: number; lng: number; address?: string | null }[];
  counts: { revealed: number; pending: number; pre_baked: number };
}

/** Live, unsaved edits previewed on the map before a correction is saved. */
export type PlacementOverrides = Partial<
  Pick<PlacementRecord, "rotationDegrees" | "scale" | "position">
>;
