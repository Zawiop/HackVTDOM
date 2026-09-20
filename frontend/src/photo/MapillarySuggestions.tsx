import { useEffect, useState } from "react";

import { lookupMapillary } from "../api/client";
import type { MapillaryPhoto } from "../types/contract";

interface Props {
  /** The located building. Null until steps 01/02 resolve one. */
  lat: number | null;
  lng: number | null;
  /** Fires when the user adopts a capture, as a File ready for step 05. */
  onPick: (file: File) => void;
}

/**
 * Step 03, path B — street-level imagery near the building.
 *
 * A convenience layer on top of the upload, nothing more. `03-photo-input.md` is
 * explicit that manual upload is the required path and that an empty result
 * should "silently fall through": most addresses have no coverage, so this
 * renders nothing at all rather than an error. A failed lookup is deliberately
 * indistinguishable from an empty one for the same reason.
 *
 * Picking a capture downloads the bytes rather than passing the URL along — the
 * thumbnail is a signed Facebook CDN link that expires, so a persisted
 * reference to it would rot.
 */
export default function MapillarySuggestions({ lat, lng, onPick }: Props) {
  const [photos, setPhotos] = useState<MapillaryPhoto[]>([]);
  const [looking, setLooking] = useState(false);
  const [chosen, setChosen] = useState<string | null>(null);
  const [fetching, setFetching] = useState<string | null>(null);

  useEffect(() => {
    if (lat === null || lng === null) {
      setPhotos([]);
      return;
    }

    const controller = new AbortController();
    setLooking(true);
    setChosen(null);

    lookupMapillary(lat, lng, controller.signal)
      .then((result) => setPhotos(result.photos))
      .catch(() => setPhotos([]))
      .finally(() => setLooking(false));

    return () => controller.abort();
  }, [lat, lng]);

  async function adopt(photo: MapillaryPhoto) {
    setFetching(photo.id);
    try {
      const blob = await fetch(photo.url).then((r) => r.blob());
      onPick(new File([blob], `mapillary-${photo.id}.jpg`, { type: "image/jpeg" }));
      setChosen(photo.id);
    } catch {
      // The CDN link may already have expired. Upload is still right there.
      setChosen(null);
    } finally {
      setFetching(null);
    }
  }

  if (looking) return <p className="hint">checking for street-level imagery…</p>;
  if (photos.length === 0) return null;

  return (
    <div className="mapillary" data-testid="mapillary-suggestions">
      <h3>found nearby</h3>
      <p className="hint">Optional — use one of these instead of uploading.</p>

      <ul className="mapillary-grid">
        {photos.slice(0, 4).map((photo) => (
          <li key={photo.id}>
            <button
              type="button"
              aria-pressed={chosen === photo.id}
              disabled={fetching !== null}
              onClick={() => adopt(photo)}
            >
              <img src={photo.url} alt={`Street-level capture ${photo.id}`} loading="lazy" />
              <span className="mono-sm">
                {photo.distanceMeters !== null && `${Math.round(photo.distanceMeters)} m`}
                {photo.capturedAt !== null &&
                  ` · ${new Date(photo.capturedAt).toISOString().slice(0, 7)}`}
              </span>
            </button>
          </li>
        ))}
      </ul>

      <p className="mono-sm">
        Imagery © Mapillary contributors
      </p>
    </div>
  );
}
