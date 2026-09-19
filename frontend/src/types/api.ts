/** Shapes returned by the backend photo + world-state routes. */

export type PhotoSource = 'upload' | 'mapillary';

export interface SourcePhoto {
  source: PhotoSource;
  id: string;
  url: string;
  mimeType?: string;
  sizeBytes?: number;
  capturedAt?: string | null;
  location?: { lat: number; lng: number } | null;
  originalName?: string;
  distanceMeters?: number;
}

export interface SourcePhotoResult {
  photos: SourcePhoto[];
  primary: SourcePhoto | null;
  requiresManualUpload: boolean;
  mapillary: { attempted: boolean; found: number; attempts: number; bbox?: string; error?: string };
}

export interface PhotoConstraints {
  maxFiles: number;
  maxFileBytes: number;
  acceptedMimeTypes: string[];
  multiple: boolean;
}

export type WorldState = 'reclaimed' | 'flooded' | 'scorched' | 'buried' | 'petrified';

export interface WorldStateOption {
  id: WorldState;
  label: string;
  blurb: string;
  spectrumPosition: number;
}

/**
 * Note what this does NOT contain: the prompt text. Spec 04 keeps the five
 * locked strings server-side, so the browser never holds one and can never
 * send one back.
 */
export interface WorldStateListResponse {
  states: WorldStateOption[];
  order: WorldState[];
  spectrum: { from: string; to: string };
}

/** What the frontend sends. `worldState` is an enum; there is no prompt field. */
export interface WorldStateSelection {
  worldState: WorldState | null;
  freeformOverride: string | null;
}
