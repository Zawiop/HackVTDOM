import { useCallback, useEffect, useMemo, useRef, useState } from "react";

/**
 * Three ways to hand over a photograph: camera, photo library, file picker.
 *
 * Why three inputs rather than one: `capture` is an attribute, not a runtime
 * call. A single `<input type="file" accept="image/*">` on a phone opens an
 * action sheet and leaves the choice buried a tap deeper, and adding
 * `capture="environment"` to *that* input takes the library away entirely.
 * Separate hidden inputs give each route its own element, so each can carry
 * exactly the attributes it needs and the user picks in our UI instead of the
 * OS's.
 *
 * This is the platform mechanism, not a polyfill: `capture` is what both iOS
 * Safari and Android Chrome honour to open the camera directly, and it needs
 * no permission prompt of our own and no getUserMedia stream. A desktop
 * browser ignores `capture` and opens its normal file picker, which is the
 * right fallback and the reason "Take Photo" is hidden rather than broken
 * where there is no camera to open.
 */

export const ACCEPTED_IMAGE_TYPES = [
  "image/jpeg",
  "image/png",
  "image/webp",
  "image/heic",
  "image/heif",
] as const;

/** Generous enough for a modern phone camera, small enough to refuse a video. */
export const MAX_FILE_BYTES = 25 * 1024 * 1024;
export const MAX_FILES = 8;

export interface RejectedFile {
  name: string;
  reason: string;
}

interface Props {
  onChange: (files: File[]) => void;
  /** Files already chosen, so a second pick can append rather than replace. */
  value: File[];
  disabled?: boolean;
}

/** iOS reports HEIC with an empty `type` often enough to be worth allowing by extension. */
const IMAGE_EXTENSION = /\.(jpe?g|png|webp|heic|heif)$/i;

function describeSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Accept only real images, and only plausible ones.
 *
 * The MIME type on the File object is supplied by the browser from the OS, not
 * by the page, but it is still worth checking both it and the extension: a
 * `.heic` off an iPhone frequently arrives with an empty type, and something
 * arriving as `video/quicktime` from the camera roll should not be uploaded as
 * a building photograph.
 */
export function validateFiles(
  incoming: File[],
  existingCount: number,
): { accepted: File[]; rejected: RejectedFile[] } {
  const accepted: File[] = [];
  const rejected: RejectedFile[] = [];

  for (const file of incoming) {
    const typeOk = (ACCEPTED_IMAGE_TYPES as readonly string[]).includes(file.type);
    const extensionOk = IMAGE_EXTENSION.test(file.name);

    if (!typeOk && !extensionOk) {
      rejected.push({ name: file.name, reason: "not an image" });
      continue;
    }
    if (file.size === 0) {
      rejected.push({ name: file.name, reason: "empty file" });
      continue;
    }
    if (file.size > MAX_FILE_BYTES) {
      rejected.push({
        name: file.name,
        reason: `too large (${describeSize(file.size)}, max ${describeSize(MAX_FILE_BYTES)})`,
      });
      continue;
    }
    if (existingCount + accepted.length >= MAX_FILES) {
      rejected.push({ name: file.name, reason: `over the ${MAX_FILES}-photo limit` });
      continue;
    }
    accepted.push(file);
  }

  return { accepted, rejected };
}

/** A camera worth offering: a touch device, which is where `capture` does anything. */
function useHasCamera(): boolean {
  return useMemo(() => {
    if (typeof window === "undefined") return false;
    const coarse = window.matchMedia?.("(pointer: coarse)").matches ?? false;
    const touch = navigator.maxTouchPoints > 0;
    return coarse || touch;
  }, []);
}

export default function PhotoSourcePicker({ onChange, value, disabled }: Props) {
  const cameraRef = useRef<HTMLInputElement | null>(null);
  const libraryRef = useRef<HTMLInputElement | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);
  const [rejected, setRejected] = useState<RejectedFile[]>([]);
  const [previews, setPreviews] = useState<string[]>([]);
  const hasCamera = useHasCamera();

  // Object URLs leak if they are not revoked; regenerate on every change and
  // clean up the previous batch.
  //
  // Guarded because a thumbnail is a nicety and the upload is the feature: a
  // context without the object-URL API (older embedded webviews, some test
  // environments) should lose the previews, not the ability to send a photo.
  useEffect(() => {
    if (typeof URL.createObjectURL !== "function") {
      setPreviews([]);
      return;
    }
    const urls = value.map((file) => URL.createObjectURL(file));
    setPreviews(urls);
    return () => urls.forEach((url) => URL.revokeObjectURL?.(url));
  }, [value]);

  const accept = useCallback(
    (list: FileList | null) => {
      const { accepted, rejected: bad } = validateFiles(Array.from(list ?? []), value.length);
      setRejected(bad);
      if (accepted.length > 0) onChange([...value, ...accepted]);
    },
    [onChange, value],
  );

  const remove = useCallback(
    (index: number) => onChange(value.filter((_, i) => i !== index)),
    [onChange, value],
  );

  // Resetting the input's value matters: picking the same file twice in a row
  // fires no change event otherwise, which reads as the button being broken.
  const open = (ref: React.RefObject<HTMLInputElement | null>) => {
    if (ref.current) {
      ref.current.value = "";
      ref.current.click();
    }
  };

  const accepted = ACCEPTED_IMAGE_TYPES.join(",");

  return (
    <div className="photo-picker">
      <span className="hint">photo of the building (required)</span>

      <div className={`photo-picker-actions${hasCamera ? "" : " is-desktop"}`}>
        {hasCamera && (
          <button
            type="button"
            className="photo-source photo-source-primary"
            onClick={() => open(cameraRef)}
            disabled={disabled}
          >
            <CameraIcon />
            <span>Take Photo</span>
          </button>
        )}

        <button
          type="button"
          className="photo-source"
          onClick={() => open(libraryRef)}
          disabled={disabled}
        >
          <LibraryIcon />
          <span>{hasCamera ? "Choose Photo" : "Choose Image"}</span>
        </button>

        <button
          type="button"
          className="photo-source"
          onClick={() => open(fileRef)}
          disabled={disabled}
        >
          <FileIcon />
          <span>Upload File</span>
        </button>
      </div>

      {/*
        Three inputs, three jobs. `capture="environment"` asks for the rear
        camera, which is the one pointed at a building. The library input must
        NOT carry `capture` or the OS skips straight past the photo roll.
      */}
      <input
        ref={cameraRef}
        type="file"
        accept="image/*"
        capture="environment"
        hidden
        onChange={(e) => accept(e.target.files)}
        data-testid="photo-camera-input"
      />
      <input
        ref={libraryRef}
        type="file"
        accept="image/*"
        multiple
        hidden
        onChange={(e) => accept(e.target.files)}
        data-testid="photo-library-input"
      />
      <input
        ref={fileRef}
        type="file"
        accept={accepted}
        multiple
        hidden
        onChange={(e) => accept(e.target.files)}
        data-testid="photo-file-input"
      />

      {previews.length > 0 && (
        <ul className="photo-thumbs" data-testid="photo-thumbs">
          {previews.map((url, i) => (
            <li key={`${value[i]?.name}-${i}`}>
              <img src={url} alt={`Selected photograph ${i + 1}`} />
              <button
                type="button"
                className="photo-thumb-remove"
                onClick={() => remove(i)}
                disabled={disabled}
                aria-label={`Remove photo ${i + 1}`}
              >
                ×
              </button>
              {i === 0 && <span className="photo-thumb-tag">front</span>}
            </li>
          ))}
        </ul>
      )}

      {rejected.length > 0 && (
        <ul className="photo-rejected" role="alert">
          {rejected.map((r) => (
            <li key={r.name}>
              {r.name} — {r.reason}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/* Inline SVGs rather than an icon dependency: three glyphs is not a library. */

function CameraIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M4 7h3l1.5-2h7L17 7h3v12H4z" />
      <circle cx="12" cy="13" r="3.5" />
    </svg>
  );
}

function LibraryIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <rect x="3" y="5" width="15" height="12" rx="1.5" />
      <path d="M6 14l3.5-4 3 3.5L15 11l3 4" />
      <path d="M21 8v11H8" />
    </svg>
  );
}

function FileIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M13 3H7a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1V8z" />
      <path d="M13 3v5h5" />
    </svg>
  );
}
