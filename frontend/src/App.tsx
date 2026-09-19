import { useCallback, useMemo, useRef, useState } from "react";
import type { Map as MapLibreMap } from "maplibre-gl";

import MapView from "./map/MapView";
import type { PropagateState } from "./map/MapView";
import { useGenerations } from "./map/useGenerations";
import { UP_AXIS_ROLL } from "./map/layers";
import BuildingPanel from "./panel/BuildingPanel";
import PropagatePanel from "./propagate/PropagatePanel";
import EntryPanel from "./entry/EntryPanel";
import WorldStatePanel from "./worldstate/WorldStatePanel";
import type { LocatedPlace } from "./entry/EntryPanel";
import { offsetMeters } from "./lib/geo";
import type {
  FootprintCandidate,
  Generation,
  PlacementOverrides,
} from "./types/contract";

/**
 * Scorched Nebraska.
 *
 * Steps 01-02 (address → footprint) run in the left panel; steps 09-12
 * (persistence, map, correction, propagate) own the map and the right panel.
 * Steps 03-08 mount alongside and write through POST /api/generations.
 */
export default function App() {
  const { rows, error, loading, refresh, replaceRow } = useGenerations();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [overrides, setOverrides] = useState<PlacementOverrides | null>(null);
  const [propagate, setPropagate] = useState<PropagateState | null>(null);
  const [satellite, setSatellite] = useState(false);
  const [showLabels, setShowLabels] = useState(true);
  const [clickedPoint, setClickedPoint] = useState<{ lat: number; lng: number } | null>(null);
  // Step 02's neighbours, kept so propagate never re-fetches them.
  const [neighbors, setNeighbors] = useState<FootprintCandidate[]>([]);
  // The building steps 01/02 resolved, which step 04's picker generates against.
  const [located, setLocated] = useState<LocatedPlace | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);

  const selected = useMemo(
    () => rows.find((r) => r.id === selectedId) ?? null,
    [rows, selectedId],
  );

  const onSelect = useCallback((row: Generation | null) => {
    setSelectedId(row?.id ?? null);
    setOverrides(null);
  }, []);

  const closePanel = useCallback(() => {
    setSelectedId(null);
    setOverrides(null);
  }, []);

  // A saved correction replaces the row in place — no full refetch needed.
  const onSaved = useCallback(
    (updated: Generation) => {
      replaceRow(updated);
      setOverrides(null);
    },
    [replaceRow],
  );

  /** Step 01/02 finished: fly there and keep the neighbours for propagate. */
  const onLocated = useCallback((place: LocatedPlace) => {
    setNeighbors(place.footprint?.neighbors ?? []);
    setLocated(place);
    mapRef.current?.easeTo({
      center: [place.lng, place.lat],
      zoom: 18,
      duration: 900,
    });
  }, []);

  /** The pitch's strongest beat: zoom out so the whole propagated area shows. */
  const revealArea = useCallback((source: Generation, radiusMeters: number) => {
    const map = mapRef.current;
    if (!map) return;
    const pad = radiusMeters * 1.4;
    const [nLat, eLng] = offsetMeters(source.lat, source.lng, pad, pad);
    const [sLat, wLng] = offsetMeters(source.lat, source.lng, -pad, -pad);
    map.fitBounds(
      [
        [wLng, sLat],
        [eLng, nLat],
      ],
      { padding: 80, pitch: 50, duration: 1400 },
    );
  }, []);

  const counts = useMemo(() => {
    const low = rows.filter((r) => r.confidence_state === "auto-low").length;
    const fixed = rows.filter((r) => r.confidence_state === "manually-verified").length;
    return { total: rows.length, low, fixed };
  }, [rows]);

  return (
    <div className="app-shell">
      {error && (
        <div className="error-banner">
          backend unreachable — {error.message}
          <button className="inline-retry" onClick={refresh}>retry</button>
        </div>
      )}

      <MapView
        rows={rows}
        selectedId={selectedId}
        onSelect={onSelect}
        roll={UP_AXIS_ROLL}
        overrides={overrides}
        propagate={propagate}
        satellite={satellite}
        showLabels={showLabels}
        onMapReady={(m) => (mapRef.current = m)}
        onMapClick={(lat, lng) => setClickedPoint({ lat, lng })}
      />

      <aside className="panel panel-left">
        <h2>SCORCHED NEBRASKA</h2>
        <div className="mono-sm">
          {loading
            ? "loading…"
            : `${counts.total} generations · ${counts.low} flagged · ${counts.fixed} verified`}
        </div>

        <EntryPanel clickedPoint={clickedPoint} onLocated={onLocated} />

        <WorldStatePanel
          address={located?.selected?.tags.name ?? located?.address ?? null}
        />

        <h3>view</h3>
        <div className="btn-grid">
          <button className={satellite ? "active" : ""} onClick={() => setSatellite((v) => !v)}>
            satellite
          </button>
          <button className={showLabels ? "active" : ""} onClick={() => setShowLabels((v) => !v)}>
            labels
          </button>
        </div>

        {selected ? (
          <PropagatePanel
            source={selected}
            neighbors={neighbors}
            onResult={(state) => {
              setPropagate(state);
              revealArea(state.source, state.radiusMeters);
            }}
            onClear={() => setPropagate(null)}
          />
        ) : (
          <>
            <h3>world propagate</h3>
            <p className="hint">Select a building to spread its World State.</p>
          </>
        )}

        <h3>legend</h3>
        <p className="hint">
          <span className="warn-text">amber ring</span> = flagged by the placement
          checker, shown rather than hidden. Click it to open the correction controls.
        </p>
      </aside>

      {selected && (
        <BuildingPanel
          row={selected}
          onClose={closePanel}
          onPreview={setOverrides}
          onSaved={onSaved}
          onPickHistory={onSelect}
          satellite={satellite}
          onToggleSatellite={() => setSatellite((v) => !v)}
        />
      )}
    </div>
  );
}
