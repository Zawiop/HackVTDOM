import { useCallback, useState } from "react";

import EntryPanel from "./entry/EntryPanel";
import MapShell from "./MapShell";
import PhotoInput from "./photo/PhotoInput";
import WorldStateSelector from "./worldstate/WorldStateSelector";
import type {
  FootprintResult,
  MapillaryPhoto,
  WorldStateSelection,
} from "./types/contract";

/**
 * Composition root. The map (steps 09-12) is the whole surface; the address
 * entry pipeline (steps 01-02) mounts inside its left panel so the two read as
 * one app rather than two stacked ones.
 *
 * Steps 03 and 04 appear under it once a building is located: the photo input
 * needs a coordinate before it can offer street-level imagery, and there is
 * nothing to transform until there is a building to transform.
 */
export default function App() {
  const [located, setLocated] = useState<{
    lat: number;
    lng: number;
    footprint: FootprintResult;
  } | null>(null);

  const [photos, setPhotos] = useState<{
    files: File[];
    mapillary: MapillaryPhoto | null;
  }>({ files: [], mapillary: null });

  const [worldState, setWorldState] = useState<WorldStateSelection>({
    worldState: null,
    freeformOverride: null,
  });

  const onLocated = useCallback(
    (lat: number, lng: number, footprint: FootprintResult) =>
      setLocated({ lat, lng, footprint }),
    [],
  );

  const ready = photos.files.length > 0 || photos.mapillary !== null;

  return (
    <MapShell
      entrySlot={
        <>
          <EntryPanel onLocated={onLocated} />

          {located && (
            <>
              <PhotoInput
                lat={located.lat}
                lng={located.lng}
                onChange={setPhotos}
              />
              <WorldStateSelector onChange={setWorldState} />

              {/*
                Step 05 takes it from here. It is handed the enum, not prompt
                text: the five locked descriptions live on the server so output
                stays consistent across every building and user.
              */}
              <p className="mono-sm">
                {ready
                  ? `Ready — ${worldState.freeformOverride ? "custom description" : worldState.worldState ?? "no world state"}`
                  : "Add a photograph to continue."}
              </p>
            </>
          )}
        </>
      }
    />
  );
}
