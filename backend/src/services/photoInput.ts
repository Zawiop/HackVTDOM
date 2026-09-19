import { fetchMapillaryPhotos } from './mapillary.js';
import { storePhotoBytes, ACCEPTED_MIME_TYPES } from './photoStore.js';
import type { SourcePhoto } from '../types/photo.js';

/**
 * getSourcePhoto (spec 03).
 *
 * Two paths, and their priority is not symmetric:
 *
 *   Path A — manual upload. The real, required path. Accepts *one or more*
 *            photographs, per the spec's own wording.
 *   Path B — Mapillary auto-fetch. A convenience layer on top, nothing more.
 *
 * There is deliberately no third path. Spec 03's "What NOT to build" is explicit:
 * no synthesised or stock-photo fallback. If neither path yields a photo, the
 * correct outcome is "the user must upload one" — not an error, not a guess.
 */

export interface UploadedFile {
  buffer: Buffer;
  mimetype: string;
  originalname: string;
  size: number;
}

export interface GetSourcePhotoInput {
  /** Files from the multipart upload. May be empty. */
  uploads?: UploadedFile[];
  /** Target coordinate. Enables the Mapillary convenience layer when present. */
  lat?: number;
  lng?: number;
  /** Absolute origin used to build public URLs for stored uploads. */
  baseUrl: string;
  /** Skip the Mapillary pass entirely (e.g. the user already chose an upload). */
  skipMapillary?: boolean;
  radiusMeters?: number;
}

export interface GetSourcePhotoResult {
  /** Every usable photo, uploads first. Empty means "user must upload one". */
  photos: SourcePhoto[];
  /** The photo the pipeline should use by default: first upload, else nearest Mapillary. */
  primary: SourcePhoto | null;
  /** True when the user still has to supply a photo before step 05 can run. */
  requiresManualUpload: boolean;
  mapillary: {
    attempted: boolean;
    found: number;
    attempts: number;
    bbox?: string;
    /** Diagnostic only — never rendered as a user-facing error state. */
    error?: string;
  };
}

export class UnsupportedPhotoTypeError extends Error {
  constructor(public readonly mimeType: string) {
    super(
      `Unsupported photo type "${mimeType}". Accepted: ${ACCEPTED_MIME_TYPES.join(', ')}.`,
    );
    this.name = 'UnsupportedPhotoTypeError';
  }
}

export async function getSourcePhoto(
  input: GetSourcePhotoInput,
): Promise<GetSourcePhotoResult> {
  const uploads = input.uploads ?? [];

  // --- Path A: manual upload (required path) -------------------------------
  const uploaded: SourcePhoto[] = [];
  for (const file of uploads) {
    if (!ACCEPTED_MIME_TYPES.includes(file.mimetype)) {
      throw new UnsupportedPhotoTypeError(file.mimetype);
    }
    const stored = await storePhotoBytes(file.buffer, file.mimetype, input.baseUrl);
    uploaded.push({
      source: 'upload',
      id: stored.id,
      url: stored.url,
      mimeType: stored.mimeType,
      sizeBytes: stored.sizeBytes,
      originalName: file.originalname,
      capturedAt: null,
      location: null,
    });
  }

  // --- Path B: Mapillary convenience layer ---------------------------------
  // Only worth the round trip when we have a coordinate and the user hasn't
  // already given us what we need.
  const shouldTryMapillary =
    !input.skipMapillary &&
    uploaded.length === 0 &&
    typeof input.lat === 'number' &&
    typeof input.lng === 'number';

  const lookup = shouldTryMapillary
    ? await fetchMapillaryPhotos(input.lat!, input.lng!, {
        radiusMeters: input.radiusMeters,
      })
    : { attempted: false as const, photos: [] as SourcePhoto[], attempts: 0 };

  const photos = [...uploaded, ...lookup.photos];

  return {
    photos,
    primary: photos[0] ?? null,
    requiresManualUpload: photos.length === 0,
    mapillary: {
      attempted: lookup.attempted,
      found: lookup.photos.length,
      attempts: lookup.attempts,
      ...('bbox' in lookup && lookup.bbox ? { bbox: lookup.bbox } : {}),
      ...('error' in lookup && lookup.error ? { error: lookup.error } : {}),
    },
  };
}
