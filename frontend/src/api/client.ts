import type {
  FootprintResult,
  GenerateImageResult,
  GenerateMeshResult,
  GeocodeResult,
} from "../types/contract";

// Empty by default so requests go through Vite's /api proxy — no CORS in dev.
const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

export class ApiError extends Error {}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ApiError(body?.detail ?? `Request failed (HTTP ${response.status})`);
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

/**
 * Step 05. Slow (~30-60 s on the free HF queue): show progress, and on ApiError offer a retry
 * (the backend answers 502/504 with `retryable: true` rather than hanging).
 */
export function generateImage(
  photo: Blob,
  worldStatePrompt: string,
  signal?: AbortSignal,
) {
  const form = new FormData();
  form.append("photo", photo);
  form.append("worldStatePrompt", worldStatePrompt);
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
export function generateMesh(
  imageUrl: string,
  footprint?: { footprintWidthMeters: number; footprintDepthMeters: number },
  signal?: AbortSignal,
) {
  return request<GenerateMeshResult>("/api/generate-mesh", {
    method: "POST",
    body: JSON.stringify({ imageUrl, ...footprint }),
    signal,
  });
}
