import { useCallback, useMemo, useRef, useState } from "react";
import type { Map as MapLibreMap } from "maplibre-gl";

import MapView from "./map/MapView";
import type { PropagateState } from "./map/MapView";
import ViewBar from "./map/ViewBar";
import { useGenerations } from "./map/useGenerations";
import { usePinnedStates } from "./map/usePinnedStates";
import { useTour } from "./map/useTour";
import { readInitialUrlState, useUrlSync } from "./map/useUrlState";
import { clampReveal, UP_AXIS_ROLL, visibleRows } from "./map/layers";
import type { GhostBuilding } from "./map/layers";
import { downloadCanvas, postcardFilename } from "./map/postcard";
import BuildingPanel from "./panel/BuildingPanel";
import BuildingRoster, { shortName } from "./panel/BuildingRoster";
import Section from "./panel/Section";
import PropagatePanel from "./propagate/PropagatePanel";
import EntryPanel from "./entry/EntryPanel";
import WorldStatePanel from "./worldstate/WorldStatePanel";
import WorldPanel from "./world/WorldPanel";
import UndoBanner from "./world/UndoBanner";
import { useUndo } from "./world/useUndo";
import type { LocatedPlace } from "./entry/EntryPanel";
import { offsetMeters } from "./lib/geo";
import { computePlacement, generateMesh, saveGeneration } from "./api/client";
import type { SideView } from "./api/client";
import type {
  FootprintCandidate,
  GenerateImageResult,
  Generation,
  PlacementOverrides,
  PlacementRecord,
} from "./types/contract";

// Read before React mounts: the first camera and selection come from the URL,
// and anything that writes to the URL later must not get there first.
const INITIAL_URL = readInitialUrlState();

/**
 * Scorched Nebraska.
 *
 * Steps 01-02 (address → footprint) run in the left panel; steps 09-12
 * (persistence, map, correction, propagate) own the map and the right panel.
 * Steps 03-08 mount alongside and write through POST /api/generations.
 */
export default function App() {
  const { rows, error, loading, refresh, replaceRow } = useGenerations();
  const { pinnedIds, pin, unpin, isPinned } = usePinnedStates(rows);
  const [selectedId, setSelectedId] = useState<string | null>(INITIAL_URL.buildingId);
  const [overrides, setOverrides] = useState<PlacementOverrides | null>(null);
  const [propagate, setPropagate] = useState<PropagateState | null>(null);
  const [satellite, setSatellite] = useState(INITIAL_URL.satellite ?? false);
  const [showLabels, setShowLabels] = useState(INITIAL_URL.labels ?? true);
  const [reveal, setReveal] = useState(clampReveal(INITIAL_URL.reveal ?? 1));
  const [clickedPoint, setClickedPoint] = useState<{ lat: number; lng: number } | null>(null);
  // Step 02's neighbours, kept so propagate never re-fetches them.
  const [neighbors, setNeighbors] = useState<FootprintCandidate[]>([]);
  // The building steps 01/02 resolved, which step 04's picker generates against.
  const [located, setLocated] = useState<LocatedPlace | null>(null);
  const [mapReady, setMapReady] = useState(false);
  const mapRef = useRef<MapLibreMap | null>(null);
  // Steps 06-08 + 11, after step 05 returns the image.
  const [pipeline, setPipeline] = useState<string | null>(null);
  const [pipelineError, setPipelineError] = useState<string | null>(null);
  const [ghost, setGhost] = useState<GhostBuilding | null>(null);
  // Correction-by-dragging: on only while the correction controls are open.
  const [dragToPlace, setDragToPlace] = useState(false);
  const [draggedPosition, setDraggedPosition] = useState<PlacementRecord["position"] | null>(null);
  const [postcardBusy, setPostcardBusy] = useState(false);
  const captureRef = useRef<Parameters<
    NonNullable<React.ComponentProps<typeof MapView>["onCaptureReady"]>
  >[0]>(null);

  const undo = useUndo(refresh);

  const selected = useMemo(
    () => rows.find((r) => r.id === selectedId) ?? null,
    [rows, selectedId],
  );

  // Keep the address bar in step: a reload lands where you were, and the link
  // is worth handing to somebody.
  useUrlSync(mapReady ? mapRef.current : null, {
    buildingId: selectedId,
    satellite,
    labels: showLabels,
    reveal,
  });

  const onSelect = useCallback((row: Generation | null) => {
    setSelectedId(row?.id ?? null);
    setOverrides(null);
    setDraggedPosition(null);
  }, []);

  /**
   * Picking a state from a building's history also leaves it on the building.
   *
   * Selecting alone only changed what the open panel showed, so closing the
   * panel reverted the map to the newest generation and the choice looked
   * discarded. Picking is the moment the user says "this is the one", so it
   * pins too; the timeline's keep/on-map button can undo it.
   */
  const onPickHistory = useCallback(
    (row: Generation) => {
      pin(row);
      onSelect(row);
    },
    [pin, onSelect],
  );

  const togglePin = useCallback(
    (row: Generation) => (isPinned(row) ? unpin(row) : pin(row)),
    [isPinned, pin, unpin],
  );

  const closePanel = useCallback(() => {
    setSelectedId(null);
    setOverrides(null);
    setDraggedPosition(null);
  }, []);

  // A saved correction replaces the row in place — no full refetch needed.
  const onSaved = useCallback(
    (updated: Generation) => {
      replaceRow(updated);
      setOverrides(null);
      setDraggedPosition(null);
    },
    [replaceRow],
  );

  /** Anything that removed rows: refetch, and find out whether undo is on offer. */
  const onWorldChanged = useCallback(async () => {
    setSelectedId(null);
    setOverrides(null);
    setPropagate(null);
    await refresh();
    await undo.refresh();
  }, [refresh, undo]);

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

  /**
   * Step 05 produced the image; carry it the rest of the way to the map.
   *
   * mesh (06+07) -> placement (08) -> persistence (11), then select the new row so the
   * building the user just made is the one open in the panel. Each failure is reported
   * rather than leaving a generated image stranded with nothing on the map.
   */
  const onImageGenerated = useCallback(
    async (
      image: GenerateImageResult,
      sideViews?: Partial<Record<SideView, File>>,
    ) => {
      const place = located;
      const footprint = place?.selected;
      if (!place || !footprint) {
        setPipelineError("locate a building first — placement needs its real footprint");
        return;
      }
      setPipelineError(null);
      // Put a block on the map at the real footprint straight away. The two
      // model calls below take 30-90 seconds, and until there was something
      // here, a slow success and a silent failure looked identical.
      setGhost({
        lat: place.lat,
        lng: place.lng,
        widthMeters: footprint.footprintWidthMeters,
        depthMeters: footprint.footprintDepthMeters,
        rotationDegrees: footprint.rotationDegrees,
      });
      try {
        setPipeline(
          sideViews
            ? `reconstructing from ${Object.keys(sideViews).length + 1} views…`
            : "building the mesh…",
        );
        const mesh = await generateMesh(
          image.imageUrl,
          {
            footprintWidthMeters: footprint.footprintWidthMeters,
            footprintDepthMeters: footprint.footprintDepthMeters,
          },
          undefined,
          sideViews,
          image.worldState ?? undefined,
        );

        setPipeline("placing it on the footprint…");
        const placement = await computePlacement({
          footprint,
          meshExtentsMeters: mesh.normalization.extentsMeters,
          neighbors,
          footprintConfidence: place.footprint?.confidence ?? "auto-high",
        });

        setPipeline("saving…");
        // A map click has no geocoded address, and "map click — 37.2, -80.4" is a poor key
        // for something history groups by: prefer the matched OSM building's own name.
        const clicked = place.address?.startsWith("map click") ?? true;
        const address =
          (clicked ? footprint.tags.name : place.address) || place.address || "unknown address";
        const saved = await saveGeneration({
          address,
          lat: place.lat,
          lng: place.lng,
          source_photo: image.sourcePhotoUrl,
          artifact: image.imageUrl,
          mesh_url: mesh.meshUrl,
          world_state: image.worldState ?? null,
          placement: {
            rotationDegrees: placement.rotationDegrees,
            scale: placement.scale,
            scaleXYZ: placement.scaleXYZ,
            position: placement.position,
            confidence: placement.confidence,
            scoredRotationCandidates: placement.scoredRotationCandidates,
          },
        });

        await refresh();
        setSelectedId(saved.id);
        setPipeline(
          mesh.provider === "placeholder"
            ? "on the map — mesh generation was unavailable, so this uses the placeholder"
            : "on the map",
        );
      } catch (err) {
        setPipeline(null);
        setPipelineError(err instanceof Error ? err.message : String(err));
      } finally {
        setGhost(null);
      }
    },
    [located, neighbors, refresh],
  );

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

  // One stop per building, in the order the roster lists them.
  const tourStops = useMemo(
    () =>
      visibleRows(rows, null, pinnedIds).sort((a, b) =>
        shortName(a.address).localeCompare(shortName(b.address)),
      ),
    [rows, pinnedIds],
  );
  const tour = useTour(mapReady ? mapRef.current : null, tourStops, {
    onArrive: (row) => {
      setSelectedId(row.id);
      setOverrides(null);
    },
  });

  const onDragPlacement = useCallback((lat: number, lng: number, done: boolean) => {
    setDraggedPosition((prev) => [lat, lng, prev?.[2] ?? 0]);
    if (done) setDragToPlace((v) => v); // keep the mode; save is still explicit
  }, []);

  const onPostcard = useCallback(async () => {
    const capture = captureRef.current;
    if (!capture) return;
    setPostcardBusy(true);
    try {
      const caption = selected
        ? shortName(selected.address)
        : "Scorched Nebraska";
      const subtitle = selected
        ? `${selected.world_state ?? "no world state"} · ${Number(selected.lat).toFixed(4)}, ${Number(selected.lng).toFixed(4)}`
        : `${rows.length} building${rows.length === 1 ? "" : "s"}`;
      const canvas = await capture({ caption, subtitle });
      if (canvas) downloadCanvas(canvas, postcardFilename(caption));
      else console.warn("[postcard] nothing was captured");
    } finally {
      setPostcardBusy(false);
    }
  }, [selected, rows.length]);

  const onCaptureReady = useCallback(
    (fn: typeof captureRef.current) => {
      captureRef.current = fn;
    },
    [],
  );

  const onMapReady = useCallback((map: MapLibreMap) => {
    mapRef.current = map;
    setMapReady(true);
  }, []);

  const counts = useMemo(() => {
    const low = rows.filter((r) => r.confidence_state === "auto-low").length;
    const fixed = rows.filter((r) => r.confidence_state === "manually-verified").length;
    const buildings = new Set(rows.map((r) => r.address)).size;
    return { total: rows.length, low, fixed, buildings };
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
        pinnedIds={pinnedIds}
        selectedId={selectedId}
        onSelect={onSelect}
        roll={UP_AXIS_ROLL}
        overrides={overrides}
        propagate={propagate}
        satellite={satellite}
        showLabels={showLabels}
        reveal={reveal}
        ghost={ghost}
        initialCamera={INITIAL_URL}
        dragToPlace={dragToPlace}
        onDragPlacement={onDragPlacement}
        onCaptureReady={onCaptureReady}
        onMapReady={onMapReady}
        onMapClick={(lat, lng) => setClickedPoint({ lat, lng })}
      />

      <aside className="panel panel-left">
        <header className="brand">
          <h1>SCORCHED NEBRASKA</h1>
          <div className="mono-sm muted">
            {loading
              ? "loading…"
              : `${counts.buildings} building${counts.buildings === 1 ? "" : "s"} · ${counts.total} state${counts.total === 1 ? "" : "s"}`}
          </div>
          {(counts.low > 0 || counts.fixed > 0) && (
            <div className="chips">
              {counts.low > 0 && <span className="chip warn">{counts.low} flagged</span>}
              {counts.fixed > 0 && <span className="chip ok">{counts.fixed} verified</span>}
            </div>
          )}
        </header>

        <Section title="create" defaultOpen>
          <EntryPanel clickedPoint={clickedPoint} onLocated={onLocated} />
          <WorldStatePanel
            address={located?.selected?.tags.name ?? located?.address ?? null}
            lat={located?.lat ?? null}
            lng={located?.lng ?? null}
            onGenerated={onImageGenerated}
          />
          {pipeline && <div className="mono-sm pipeline">{pipeline}</div>}
          {pipelineError && <div className="mono-sm error-text">{pipelineError}</div>}
        </Section>

        {rows.length > 0 && (
          <Section title="buildings" badge={counts.buildings} defaultOpen>
            <BuildingRoster
              rows={rows}
              selectedId={selectedId}
              pinnedIds={pinnedIds}
              onSelect={onSelect}
            />
          </Section>
        )}

        <Section title="propagate" defaultOpen={false}>
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
            <p className="hint">Select a building to spread its World State.</p>
          )}
        </Section>

        <Section title="world" defaultOpen={rows.length === 0}>
          <WorldPanel count={counts.total} onChanged={onWorldChanged} />
        </Section>

        <Section title="legend" defaultOpen={false}>
          <p className="hint">
            <span className="warn-text">ringed</span> = flagged by the placement
            checker, shown rather than hidden. Click it to open the correction
            controls.
            <br />
            <span className="verified-text">✓ verified</span> = a human corrected it.
          </p>
        </Section>
      </aside>

      <ViewBar
        reveal={reveal}
        onReveal={setReveal}
        satellite={satellite}
        onToggleSatellite={() => setSatellite((v) => !v)}
        labels={showLabels}
        onToggleLabels={() => setShowLabels((v) => !v)}
        tour={tour}
        postcardBusy={postcardBusy}
        onPostcard={onPostcard}
        disabled={rows.length === 0}
      />

      {undo.offering && (
        <UndoBanner
          info={undo.info}
          busy={undo.busy}
          error={undo.error}
          onUndo={() => void undo.undo()}
          onDismiss={undo.dismiss}
        />
      )}

      {selected && (
        <BuildingPanel
          row={selected}
          onClose={closePanel}
          onPreview={setOverrides}
          onSaved={onSaved}
          onPickHistory={onPickHistory}
          isPinned={isPinned}
          onTogglePin={togglePin}
          onRemoved={onWorldChanged}
          onCorrectionToggle={setDragToPlace}
          draggedPosition={draggedPosition}
          satellite={satellite}
          onToggleSatellite={() => setSatellite((v) => !v)}
        />
      )}
    </div>
  );
}
