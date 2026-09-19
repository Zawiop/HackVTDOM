import { createHash, randomUUID } from 'node:crypto';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

/**
 * Where uploaded photos live until step 11 wires up Supabase storage.
 *
 * Deliberately a single narrow seam: everything else in the photo module calls
 * `storePhotoBytes` and gets back a public URL, so swapping local disk for a
 * Supabase bucket later is one function body, not a refactor.
 */

const UPLOAD_DIR = path.resolve(process.cwd(), 'uploads');

/** Matches the static mount in server.ts. */
export const PUBLIC_UPLOAD_PATH = '/uploads';

const EXT_BY_MIME: Record<string, string> = {
  'image/jpeg': '.jpg',
  'image/png': '.png',
  'image/webp': '.webp',
  'image/heic': '.heic',
  'image/heif': '.heif',
};

export const ACCEPTED_MIME_TYPES = Object.keys(EXT_BY_MIME);

export interface StoredPhoto {
  id: string;
  filename: string;
  url: string;
  absolutePath: string;
  sizeBytes: number;
  mimeType: string;
  /** Content hash, so re-uploading the same photo is recognisable downstream. */
  sha256: string;
}

export async function storePhotoBytes(
  bytes: Buffer,
  mimeType: string,
  baseUrl: string,
): Promise<StoredPhoto> {
  await mkdir(UPLOAD_DIR, { recursive: true });

  const id = randomUUID();
  const ext = EXT_BY_MIME[mimeType] ?? '.bin';
  const filename = `${id}${ext}`;
  const absolutePath = path.join(UPLOAD_DIR, filename);

  await writeFile(absolutePath, bytes);

  return {
    id,
    filename,
    url: `${baseUrl.replace(/\/$/, '')}${PUBLIC_UPLOAD_PATH}/${filename}`,
    absolutePath,
    sizeBytes: bytes.byteLength,
    mimeType,
    sha256: createHash('sha256').update(bytes).digest('hex'),
  };
}

export { UPLOAD_DIR };
