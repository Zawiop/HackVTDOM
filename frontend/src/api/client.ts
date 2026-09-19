import type { FootprintResult, GeocodeResult } from "../types/contract";

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

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
