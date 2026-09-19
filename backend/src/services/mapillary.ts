import { env, hasMapillary } from '../config/env.js';
import { bboxAround, bboxToParam, haversineMeters } from '../geo/latlng.js';
import type { MapillaryImage, MapillaryLookupResult, SourcePhoto } from '../types/photo.js';

const MAPILLARY_IMAGES_URL = 'https://graph.mapillary.com/images';

/** Field names verified live 2026-09-19 — see VERIFIED CAPTURE in markdown_files/03-photo-input.md. */
const FIELDS = ['id', 'thumb_2048_url', 'thumb_1024_url', 'geometry', 'captured_at'] as const;

/** Spec 03 says "a small box (~30-50m)"; 40m is the middle of that range. */
export const DEFAULT_RADIUS_METERS = 40;

/**
 * Verified live: `graph.mapillary.com/images` returns *non-deterministic* counts
 * for byte-identical bbox queries — five consecutive identical requests to a
 * known-dense area returned 0, 2, 5, 6, 5 images. So a single empty `data` array
 * is frequently a false negative rather than genuine absence of coverage.
 *
 * The fix is to retry at the spec'd radius before concluding "no imagery", then
 * make one wider pass. Widening is deliberately last and modest: imagery 100m
 * away may well be of a *different* building, and this photo feeds image
 * generation, so relevance matters more than hit rate. Results are ranked by
 * true distance from the target so the nearest capture always wins.
 */
const ATTEMPT_RADII = [DEFAULT_RADIUS_METERS, DEFAULT_RADIUS_METERS, 100];

/** Mapillary occasionally hangs; the convenience layer must never block upload. */
const TIMEOUT_MS = 8000;

export interface MapillaryOptions {
  radiusMeters?: number;
  limit?: number;
  signal?: AbortSignal;
}

function toSourcePhoto(img: MapillaryImage, target: { lat: number; lng: number }): SourcePhoto | null {
  const url = img.thumb_2048_url ?? img.thumb_1024_url;
  if (!url) return null;

  const coords = img.geometry?.coordinates;
  // Mapillary geometry is GeoJSON order: [lng, lat].
  const location =
    Array.isArray(coords) && coords.length === 2
      ? { lat: coords[1]!, lng: coords[0]! }
      : null;

  return {
    source: 'mapillary',
    id: String(img.id),
    url,
    mimeType: 'image/jpeg',
    capturedAt:
      typeof img.captured_at === 'number' ? new Date(img.captured_at).toISOString() : null,
    location,
    distanceMeters: location ? haversineMeters(target, location) : undefined,
  };
}

async function requestOnce(
  lat: number,
  lng: number,
  radius: number,
  limit: number,
  signal: AbortSignal,
): Promise<{ bbox: string; images: MapillaryImage[] }> {
  const bbox = bboxToParam(bboxAround(lat, lng, radius));

  const url = new URL(MAPILLARY_IMAGES_URL);
  url.searchParams.set('fields', FIELDS.join(','));
  url.searchParams.set('bbox', bbox);
  url.searchParams.set('limit', String(limit));

  const res = await fetch(url, {
    // Token as a bearer header rather than a query param, so it never lands in a
    // proxy or access log. Spec 03 permits either.
    headers: { Authorization: `OAuth ${env.mapillaryAccessToken}` },
    signal,
  });

  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(`Mapillary HTTP ${res.status}: ${body.slice(0, 200)}`);
  }

  const json = (await res.json()) as { data?: MapillaryImage[] };
  return { bbox, images: Array.isArray(json.data) ? json.data : [] };
}

/**
 * Look for street-level imagery near a point (spec 03, path B).
 *
 * This is a convenience layer, not a fallback of last resort. An empty result is
 * a normal, expected outcome — coverage is patchy — so this never throws and
 * never produces a user-facing error state. Callers fall through to requiring a
 * manual upload, which is the actual required path.
 */
export async function fetchMapillaryPhotos(
  lat: number,
  lng: number,
  opts: MapillaryOptions = {},
): Promise<MapillaryLookupResult> {
  if (!hasMapillary()) {
    return { attempted: false, photos: [], attempts: 0 };
  }

  const limit = opts.limit ?? 10;
  // An explicit radius from the caller disables the widening ladder — they asked
  // for a specific box, honour it (but still retry through the flaky index).
  const radii = opts.radiusMeters
    ? [opts.radiusMeters, opts.radiusMeters]
    : ATTEMPT_RADII;

  const timeout = AbortSignal.timeout(TIMEOUT_MS);
  const signal = opts.signal ? AbortSignal.any([opts.signal, timeout]) : timeout;

  const byId = new Map<string, SourcePhoto>();
  let lastBbox: string | undefined;
  let lastError: string | undefined;
  let attempts = 0;

  for (const radius of radii) {
    attempts++;
    try {
      const { bbox, images } = await requestOnce(lat, lng, radius, limit, signal);
      lastBbox = bbox;
      for (const img of images) {
        const photo = toSourcePhoto(img, { lat, lng });
        if (photo && !byId.has(photo.id)) byId.set(photo.id, photo);
      }
      // Stop as soon as we have something usable; the extra passes exist only to
      // beat the flaky index, not to vacuum up every photo in the area.
      if (byId.size > 0) break;
    } catch (err) {
      lastError = err instanceof Error ? err.message : String(err);
      // An aborted/timed-out request won't recover on retry — stop early.
      if (signal.aborted) break;
    }
  }

  const photos = [...byId.values()].sort((a, b) => {
    const da = a.distanceMeters ?? Number.POSITIVE_INFINITY;
    const db = b.distanceMeters ?? Number.POSITIVE_INFINITY;
    if (Math.abs(da - db) > 1) return da - db; // nearest capture first
    return (b.capturedAt ?? '').localeCompare(a.capturedAt ?? ''); // then newest
  });

  return {
    attempted: true,
    photos,
    attempts,
    bbox: lastBbox,
    // Diagnostic only. Present alongside photos:[] does NOT mean "show an error";
    // the caller still just falls through to manual upload.
    ...(photos.length === 0 && lastError ? { error: lastError } : {}),
  };
}
