import type {
  Correction,
  FootprintResult,
  GeocodeResult,
  Generation,
  GenerationCreate,
  PropagateResponse,
} from "../types/contract";

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

export class ApiError extends Error {
  status: number;
  path: string;
  constructor(message: string, status: number, path: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.path = path;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = body?.detail ?? `Request failed (HTTP ${response.status})`;
    const message = typeof detail === "string" ? detail : JSON.stringify(detail);
    console.error(`[api] ${path} -> ${response.status}: ${message}`);
    throw new ApiError(message, response.status, path);
  }
  return response.json() as Promise<T>;
}

/** Step 01. `found: false` is a normal answer, not an error. */
export function geocode(address: string, signal?: AbortSignal) {
  return request<GeocodeResult>(
    `/api/geocode?q=${encodeURIComponent(address)}`,
    { signal },
  );
}

/** Step 02. Also the entry point for the click-the-map path, which skips step 01. */
export function getFootprint(
  lat: number,
  lng: number,
  signal?: AbortSignal,
) {
  return request<FootprintResult>("/api/footprint", {
    method: "POST",
    body: JSON.stringify({ lat, lng }),
    signal,
  });
}

// --- Steps 09-11: persistence, correction, propagate ---
//
// A failed write must never look like a success in the UI (step 11), so every
// call below throws rather than resolving to null, and logs before it does.

/** Step 11 — every persisted row, the data behind the map's 3D layer. */
export function listGenerations(signal?: AbortSignal) {
  return request<Generation[]>("/api/generations", { signal });
}

export function getGeneration(id: string, signal?: AbortSignal) {
  return request<Generation>(`/api/generations/${id}`, { signal });
}

/** Step 11 — one address's sequence, oldest first: Reality → Flooded → … */
export function getHistory(address: string, signal?: AbortSignal) {
  return request<Generation[]>(
    `/api/history?address=${encodeURIComponent(address)}`,
    { signal },
  );
}

/** Step 11 — save one generation. Never an upsert; a repeat address appends. */
export function saveGeneration(payload: GenerationCreate, signal?: AbortSignal) {
  return request<Generation>("/api/generations", {
    method: "POST",
    body: JSON.stringify(payload),
    signal,
  });
}

/** Step 09 — persist a corrected transform; backend flips to manually-verified. */
export function correctGeneration(
  id: string,
  correction: Correction,
  signal?: AbortSignal,
) {
  return request<Generation>(`/api/generations/${id}/correction`, {
    method: "PATCH",
    body: JSON.stringify(correction),
    signal,
  });
}

/** Step 10 — reveal pre-baked neighbours within a radius. Never generates live. */
export function propagate(
  sourceGenerationId: string,
  radiusMeters: 50 | 100 | 250,
  neighbors: unknown[] = [],
  signal?: AbortSignal,
) {
  return request<PropagateResponse>("/api/propagate", {
    method: "POST",
    body: JSON.stringify({
      source_generation_id: sourceGenerationId,
      radius_meters: radiusMeters,
      neighbors,
    }),
    signal,
  });
}
