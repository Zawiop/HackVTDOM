import type {
  PhotoConstraints,
  SourcePhotoResult,
  WorldStateListResponse,
  WorldStateSelection,
} from '../types/api';

const API = '/api';

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as { error?: string };
    throw new Error(body.error ?? `Request failed (${res.status})`);
  }
  return res.json() as Promise<T>;
}

/**
 * Upload one or more photos, optionally letting the backend try Mapillary when
 * none are supplied. `files` is an array because spec 03 requires the input to
 * accept "one or more photographs".
 */
export async function submitSourcePhotos(opts: {
  files: File[];
  lat?: number;
  lng?: number;
  signal?: AbortSignal;
}): Promise<SourcePhotoResult> {
  const form = new FormData();
  for (const file of opts.files) form.append('photos', file);
  if (opts.lat !== undefined) form.append('lat', String(opts.lat));
  if (opts.lng !== undefined) form.append('lng', String(opts.lng));

  return json<SourcePhotoResult>(
    await fetch(`${API}/photos/source`, {
      method: 'POST',
      body: form,
      ...(opts.signal ? { signal: opts.signal } : {}),
    }),
  );
}

/** Look for existing street-level imagery before asking the user to upload. */
export async function lookupMapillary(
  lat: number,
  lng: number,
  signal?: AbortSignal,
): Promise<SourcePhotoResult['photos']> {
  const res = await fetch(`${API}/photos/mapillary?lat=${lat}&lng=${lng}`, {
    ...(signal ? { signal } : {}),
  });
  const body = await json<{ photos: SourcePhotoResult['photos'] }>(res);
  return body.photos;
}

export async function fetchPhotoConstraints(): Promise<PhotoConstraints> {
  return json<PhotoConstraints>(await fetch(`${API}/photos/constraints`));
}

export async function fetchWorldStates(): Promise<WorldStateListResponse> {
  return json<WorldStateListResponse>(await fetch(`${API}/world-states`));
}

/**
 * Resolve a selection into the prompt step 05 will use.
 *
 * The request body carries an enum and (optionally) the user's own words —
 * never a preset prompt string. That's the point of keeping them server-side.
 */
export async function resolveWorldStatePrompt(
  selection: WorldStateSelection,
): Promise<{ prompt: string; source: 'preset' | 'override'; worldState: string | null }> {
  return json(
    await fetch(`${API}/world-states/resolve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(selection),
    }),
  );
}
