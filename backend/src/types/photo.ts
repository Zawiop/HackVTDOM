/** Shared shapes for the photo-input step (spec 03). */

export type PhotoSource = 'upload' | 'mapillary';

/** One usable source photo, whichever path produced it. */
export interface SourcePhoto {
  source: PhotoSource;
  /** URL the rest of the pipeline (step 05) can fetch the bytes from. */
  url: string;
  /** Mapillary image id, or the stored filename for an upload. */
  id: string;
  mimeType?: string;
  sizeBytes?: number;
  /** Where the photo was taken, when the source knows. Mapillary only. */
  capturedAt?: string | null;
  location?: { lat: number; lng: number } | null;
  /** Original client filename, uploads only. */
  originalName?: string;
  /** Distance from the requested point, Mapillary only. Used for ranking. */
  distanceMeters?: number;
}

/** Raw Mapillary `/images` record, fields as requested in spec 03. */
export interface MapillaryImage {
  id: string;
  thumb_2048_url?: string;
  thumb_1024_url?: string;
  geometry?: { type: string; coordinates: [number, number] };
  captured_at?: number;
}

export interface MapillaryLookupResult {
  /** False when no token is configured — the convenience layer is simply off. */
  attempted: boolean;
  /** Normalised photos, newest first. Empty is the expected common case. */
  photos: SourcePhoto[];
  /** The bbox actually queried, for debugging coverage gaps. */
  bbox?: string;
  /** How many HTTP passes it took (the index is non-deterministic — see service). */
  attempts: number;
  /**
   * Set when the call itself failed (network/HTTP), as opposed to succeeding
   * with an empty `data` array. Callers still fall through to manual upload
   * either way — this is diagnostic only, never surfaced as a user error.
   */
  error?: string;
}
