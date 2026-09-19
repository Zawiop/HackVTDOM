import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { lookupMapillary } from '../api/client';
import type { MapillaryPhoto } from '../types/contract';

/** Upload limits. The backend's own multipart handler is the real gate. */
export interface PhotoConstraints {
  maxFiles: number;
  maxFileBytes: number;
  acceptedMimeTypes: string[];
  multiple: boolean;
}

/**
 * Photo input (spec 03).
 *
 * Two paths with asymmetric priority: manual upload is the required path, the
 * Mapillary suggestion strip is a convenience layer on top. The file input is
 * `multiple` — spec 03 is explicit that "one or more photographs" is not
 * satisfied by a single-file input, even if nobody ever picks two.
 *
 * There is deliberately no third path and no error state for empty Mapillary
 * results: no coverage is the normal case, and the UI just shows nothing extra.
 */

const DEFAULT_CONSTRAINTS: PhotoConstraints = {
  maxFiles: 10,
  maxFileBytes: 20 * 1024 * 1024,
  acceptedMimeTypes: ['image/jpeg', 'image/png', 'image/webp', 'image/heic', 'image/heif'],
  multiple: true,
};

export interface PhotoInputProps {
  /** Target building, when known. Enables the Mapillary suggestion strip. */
  lat?: number;
  lng?: number;
  constraints?: PhotoConstraints;
  /** Fires whenever the chosen set changes. Files are uploaded on submit. */
  onChange?: (selection: { files: File[]; mapillary: MapillaryPhoto | null }) => void;
}

interface Preview {
  file: File;
  url: string;
  key: string;
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export function PhotoInput({ lat, lng, constraints, onChange }: PhotoInputProps) {
  const limits = constraints ?? DEFAULT_CONSTRAINTS;
  const inputId = useId();
  const inputRef = useRef<HTMLInputElement>(null);

  const [previews, setPreviews] = useState<Preview[]>([]);
  const [rejected, setRejected] = useState<string[]>([]);
  const [suggestions, setSuggestions] = useState<MapillaryPhoto[]>([]);
  const [chosenSuggestion, setChosenSuggestion] = useState<MapillaryPhoto | null>(null);
  const [lookingUp, setLookingUp] = useState(false);

  // Revoke object URLs on unmount so previews don't leak.
  useEffect(() => () => previews.forEach((p) => URL.revokeObjectURL(p.url)), [previews]);

  useEffect(() => {
    onChange?.({ files: previews.map((p) => p.file), mapillary: chosenSuggestion });
  }, [previews, chosenSuggestion, onChange]);

  // Mapillary convenience pass. Failure and emptiness are indistinguishable to
  // the user on purpose — both just mean "no suggestions shown".
  useEffect(() => {
    if (lat === undefined || lng === undefined) return;
    const controller = new AbortController();
    setLookingUp(true);
    lookupMapillary(lat, lng, controller.signal)
      .then((result) => setSuggestions(result.photos))
      .catch(() => setSuggestions([]))
      .finally(() => setLookingUp(false));
    return () => controller.abort();
  }, [lat, lng]);

  const addFiles = useCallback(
    (incoming: FileList | File[]) => {
      const accepted: Preview[] = [];
      const bad: string[] = [];

      for (const file of Array.from(incoming)) {
        if (!limits.acceptedMimeTypes.includes(file.type)) {
          bad.push(`${file.name} — unsupported type (${file.type || 'unknown'})`);
          continue;
        }
        if (file.size > limits.maxFileBytes) {
          bad.push(`${file.name} — too large (${formatBytes(file.size)})`);
          continue;
        }
        accepted.push({
          file,
          url: URL.createObjectURL(file),
          key: `${file.name}:${file.size}:${file.lastModified}`,
        });
      }

      setRejected(bad);
      setPreviews((prev) => {
        const seen = new Set(prev.map((p) => p.key));
        const merged = [...prev];
        for (const p of accepted) {
          if (seen.has(p.key)) {
            URL.revokeObjectURL(p.url); // exact duplicate re-pick
            continue;
          }
          if (merged.length >= limits.maxFiles) {
            URL.revokeObjectURL(p.url);
            bad.push(`${p.file.name} — over the ${limits.maxFiles}-photo limit`);
            continue;
          }
          merged.push(p);
        }
        return merged;
      });
    },
    [limits],
  );

  const removeAt = useCallback((key: string) => {
    setPreviews((prev) => {
      const target = prev.find((p) => p.key === key);
      if (target) URL.revokeObjectURL(target.url);
      return prev.filter((p) => p.key !== key);
    });
  }, []);

  const hasPhoto = previews.length > 0 || chosenSuggestion !== null;

  return (
    <section className="photo-input" aria-labelledby={`${inputId}-heading`}>
      <h2 id={`${inputId}-heading`}>Source photograph</h2>
      <p className="photo-input__hint">
        Upload one or more photographs of the building. More angles give the mesh
        step more to work with.
      </p>

      <label
        className="photo-input__drop"
        htmlFor={inputId}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          addFiles(e.dataTransfer.files);
        }}
      >
        <input
          id={inputId}
          ref={inputRef}
          type="file"
          // The spec line this whole component exists for.
          multiple
          accept={limits.acceptedMimeTypes.join(',')}
          onChange={(e) => {
            if (e.target.files) addFiles(e.target.files);
            e.target.value = ''; // allow re-picking the same file after a remove
          }}
          data-testid="photo-file-input"
        />
        <span>Drop photos here, or choose files</span>
      </label>

      {rejected.length > 0 && (
        <ul className="photo-input__rejected" role="alert">
          {rejected.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      )}

      {previews.length > 0 && (
        <ul className="photo-input__grid" data-testid="photo-previews">
          {previews.map((p) => (
            <li key={p.key}>
              <img src={p.url} alt={p.file.name} />
              <span className="photo-input__meta">
                {p.file.name} · {formatBytes(p.file.size)}
              </span>
              <button type="button" onClick={() => removeAt(p.key)} aria-label={`Remove ${p.file.name}`}>
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}

      {/* Convenience layer. Absent silently when there's no coverage. */}
      {lookingUp && <p className="photo-input__status">Checking for street-level imagery…</p>}

      {suggestions.length > 0 && (
        <div className="photo-input__suggestions" data-testid="mapillary-suggestions">
          <h3>Found nearby on Mapillary</h3>
          <p className="photo-input__hint">
            Optional — pick one to skip uploading, or ignore these and use your own.
          </p>
          <ul>
            {suggestions.map((s) => (
              <li key={s.id}>
                <button
                  type="button"
                  aria-pressed={chosenSuggestion?.id === s.id}
                  onClick={() =>
                    setChosenSuggestion((cur: MapillaryPhoto | null) =>
                      cur?.id === s.id ? null : s,
                    )
                  }
                >
                  <img src={s.url} alt={`Street-level capture ${s.id}`} loading="lazy" />
                  <span className="photo-input__meta">
                    {s.distanceMeters !== null && `${Math.round(s.distanceMeters)} m away`}
                    {s.capturedAt !== null &&
                      ` · ${new Date(s.capturedAt).toISOString().slice(0, 10)}`}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {!hasPhoto && !lookingUp && (
        <p className="photo-input__status" data-testid="upload-required">
          A photograph is required to continue.
        </p>
      )}
    </section>
  );
}

export default PhotoInput;
