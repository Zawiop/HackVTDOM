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

/** Step 08 — placement transform */
export interface PlacementRecord {
  rotationDegrees: number;
  scale: number;
  /** [lat, lng, z] */
  position: [number, number, number];
  confidence: ConfidenceState;
  scoredRotationCandidates: { rotationDegrees: number; iou: number }[];
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
