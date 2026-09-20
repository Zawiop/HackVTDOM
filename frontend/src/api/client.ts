import type {
  ConfidenceState,
  Correction,
  FootprintCandidate,
  FootprintResult,
  GenerateImageResult,
  GenerateMeshResult,
  Generation,
  GenerationCreate,
  GeocodeResult,
  MapillaryLookup,
  PlacementResult,
  PropagateResponse,
  WorldState,
  WorldStateOption,
} from "../types/contract";

// Empty by default so requests go through Vite's /api proxy — no CORS in dev.
const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

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
  // 204 (a successful DELETE) has no body to parse.
  if (response.status === 204 || response.headers?.get("content-length") === "0") {
    return undefined as T;
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

/** Step 04 — the Present <-> Collapsed spectrum for the picker. */
export function getWorldStates(signal?: AbortSignal) {
  return request<WorldStateOption[]>("/api/worldstates", { signal });
}

/**
 * Step 05. Slow (~30-60 s on the free HF queue): show progress, and on ApiError offer a retry
 * (the backend answers 502/504 with `retryable: true` rather than hanging).
 */
export function generateImage(
  photo: Blob | Blob[],
  selection: {
    worldState?: WorldState;
    worldStatePrompt?: string;
    /** Which upload is the front view. Omit to let scoring decide. */
    frontIndex?: number;
  },
  signal?: AbortSignal,
) {
  const form = new FormData();
  // "one or more photographs" (spec 03). The backend scores them and uses the
  // sharpest, best-exposed one — they are not fused, and it reports which.
  for (const p of Array.isArray(photo) ? photo : [photo]) form.append("photo", p);
  // Step 04: send the spectrum id, not prompt text — the locked description is
  // resolved server-side. `worldStatePrompt` is the freeform override only.
  if (selection.worldState) form.append("worldState", selection.worldState);
  if (selection.worldStatePrompt?.trim()) {
    form.append("worldStatePrompt", selection.worldStatePrompt.trim());
  }
  if (typeof selection.frontIndex === "number") {
    form.append("frontIndex", String(selection.frontIndex));
  }
  // Empty headers so the browser sets the multipart boundary itself.
  return request<GenerateImageResult>("/api/generate-image", {
    method: "POST",
    body: form,
    headers: {},
    signal,
  });
}

/**
 * Steps 06+07. Pass step 02's selected footprint so the mesh comes back sized in meters.
 * Always resolves with a mesh; check `confidence` / `provider === "placeholder"`.
 */
export type SideView = "back" | "left" | "right";

export function generateMesh(
  imageUrl: string,
  footprint?: { footprintWidthMeters: number; footprintDepthMeters: number },
  signal?: AbortSignal,
  /** Extra angles of the same building. With any of these the mesh is
   *  reconstructed from every view instead of inferring the unseen sides. */
  sideViews?: Partial<Record<SideView, Blob>>,
  worldState?: string,
) {
  const sides = Object.entries(sideViews ?? {}).filter(([, b]) => b) as [SideView, Blob][];
  if (!sides.length) {
    return request<GenerateMeshResult>("/api/generate-mesh", {
      method: "POST",
      body: JSON.stringify({ imageUrl, ...footprint, worldState }),
      signal,
    });
  }
  // Side views are local files, so this leg has to be multipart; the front
  // stays a URL because the backend already has that image on disk.
  const form = new FormData();
  form.append("imageUrl", imageUrl);
  if (footprint) {
    form.append("footprintWidthMeters", String(footprint.footprintWidthMeters));
    form.append("footprintDepthMeters", String(footprint.footprintDepthMeters));
  }
  if (worldState) form.append("worldState", worldState);
  for (const [side, blob] of sides) form.append(`image_${side}`, blob);
  return request<GenerateMeshResult>("/api/generate-mesh", {
    method: "POST",
    body: form,
    headers: {},
    signal,
  });
}

/**
 * Step 08 — rotation, scale and ground position for a normalized mesh against the real
 * footprint. Pure computation on the backend: it never re-queries Overpass, so pass step
 * 02's `neighbors` straight through for the collision check.
 */
export function computePlacement(
  body: {
    footprint: FootprintCandidate;
    meshExtentsMeters: { width: number; depth: number; height: number };
    neighbors?: FootprintCandidate[];
    footprintConfidence?: ConfidenceState;
  },
  signal?: AbortSignal,
) {
  return request<PlacementResult>("/api/placement", {
    method: "POST",
    body: JSON.stringify(body),
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

/**
 * Step 03 path B. Optional: manual upload is the required path and never
 * depends on this.
 *
 * Always resolves — zero photos is the expected outcome for most addresses, so
 * check `requiresManualUpload` and render nothing rather than an error.
 */
export function lookupMapillary(lat: number, lng: number, signal?: AbortSignal) {
  return request<MapillaryLookup>(
    `/api/photo/mapillary?lat=${lat}&lng=${lng}`,
    { signal },
  );
}

/** Step 11 — remove one generation (one World State of a building). */
export function deleteGeneration(id: string, signal?: AbortSignal) {
  return request<void>(`/api/generations/${id}`, { method: "DELETE", signal });
}

/** Step 11 — remove a building entirely, every World State it has. */
export function deleteAddress(address: string, signal?: AbortSignal) {
  return request<{ address: string; removed: number }>(
    `/api/generations?address=${encodeURIComponent(address)}`,
    { method: "DELETE", signal },
  );
}

/** Step 11 — empty the world. Every building, every state. Cannot be undone. */
export function resetWorld(signal?: AbortSignal) {
  return request<{ removed: number }>("/api/world?confirm=yes", {
    method: "DELETE",
    signal,
  });
}
