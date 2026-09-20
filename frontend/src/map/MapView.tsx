import { useCallback, useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import type { Map as MapLibreMap, MapLayerMouseEvent, MapMouseEvent } from "maplibre-gl";
import { MapboxOverlay } from "@deck.gl/mapbox";
import { createBuildingLighting } from "./lighting";
import "maplibre-gl/dist/maplibre-gl.css";

import {
  BASE_STYLE,
  INITIAL_VIEW,
  OSM_LAYER_ID,
  SATELLITE_LAYER_ID,
} from "./basemap";
import {
  buildConfidenceRingLayer,
  buildGhostLayers,
  buildGroundShadowLayers,
  buildTerrainLayers,
  buildLabelLayer,
  buildPendingLayer,
  buildRadiusLayer,
  buildScenegraphLayers,
  visibleRows,
} from "./layers";
import type { GhostBuilding } from "./layers";
import { compositeCanvases } from "./postcard";
import type { PostcardOptions } from "./postcard";
import type { Generation, PlacementOverrides } from "../types/contract";

export interface PropagateState {
  active: boolean;
  source: Generation;
  radiusMeters: number;
  revealed: Generation[];
  pending: { lat: number; lng: number; address?: string | null }[];
}

export interface InitialCamera {
  center?: { lat: number; lng: number } | null;
  zoom?: number | null;
  pitch?: number | null;
  bearing?: number | null;
}

interface Props {
  rows: Generation[];
  selectedId: string | null;
  onSelect: (row: Generation | null) => void;
  roll: number;
  overrides: PlacementOverrides | null;
  propagate: PropagateState | null;
  satellite?: boolean;
  showLabels?: boolean;
  /** 0..1 — the before/after reveal. 1 is the full World State. */
  reveal?: number;
  /** A block where generation is running right now, so the wait is visible. */
  ghost?: GhostBuilding | null;
  onMapReady?: (map: MapLibreMap) => void;
  /** Clicking empty map is the step 01 "click the map instead of typing" path. */
  onMapClick?: (lat: number, lng: number) => void;
  /** Rows the user chose to leave showing; they win over "newest per address". */
  pinnedIds?: ReadonlySet<string> | null;
  /** Camera to open on, from the URL. Applied once, before the first paint. */
  initialCamera?: InitialCamera | null;
  /**
   * Dragging the selected building moves it, instead of panning the map.
   * Only on while the correction controls are open: a map you cannot pan
   * without moving a building is a worse map.
   */
  dragToPlace?: boolean;
  onDragPlacement?: (lat: number, lng: number, done: boolean) => void;
  /** Handed a function that returns the current view as a canvas. */
  onCaptureReady?: (capture: ((o?: PostcardOptions) => Promise<HTMLCanvasElement | null>) | null) => void;
}

/**
 * MapLibre base map with a deck.gl overlay on top.
 *
 * MapboxOverlay (overlaid, not interleaved) is the supported MapLibre interop
 * path and avoids depth-buffer fighting between raster tiles and 3D meshes.
 */
export default function MapView({
  rows,
  selectedId,
  onSelect,
  roll,
  overrides,
  propagate,
  satellite = false,
  showLabels = true,
  reveal = 1,
  ghost = null,
  onMapReady,
  onMapClick,
  pinnedIds = null,
  initialCamera = null,
  dragToPlace = false,
  onDragPlacement,
  onCaptureReady,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const overlayRef = useRef<MapboxOverlay | null>(null);
  // Kept in refs so the map is created exactly once, never torn down on a
  // parent re-render just because a handler identity changed.
  const clickRef = useRef(onMapClick);
  clickRef.current = onMapClick;
  const dragRef = useRef({ enabled: dragToPlace, selectedId, onDragPlacement });
  dragRef.current = { enabled: dragToPlace, selectedId, onDragPlacement };
  const draggingRef = useRef(false);

  /**
   * The current view as a single canvas.
   *
   * Both WebGL contexts keep their drawing buffers — deck.gl does by default,
   * and the map is asked for it above — so the pixels can simply be read,
   * with no need to hook the render loop and catch the frame mid-flight. One
   * repaint and one animation frame first, so a map that has been sitting
   * idle has actually drawn what is on screen.
   */
  const capture = useCallback(async (options: PostcardOptions = {}) => {
    const map = mapRef.current;
    const container = containerRef.current;
    if (!map || !container) return null;
    map.triggerRepaint();
    // Wait for a fresh frame, but only as a courtesy. A hidden or backgrounded
    // tab stops servicing requestAnimationFrame entirely, and waiting on one
    // there never returns — the button would sit on "saving…" forever. The
    // preserved buffers already hold the last frame drawn, so timing out and
    // capturing that is correct, not a fallback.
    await Promise.race([
      new Promise<void>((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
      }),
      new Promise<void>((resolve) => setTimeout(resolve, 400)),
    ]);
    const canvases = Array.from(container.querySelectorAll("canvas"));
    return compositeCanvases(canvases, options);
  }, []);

  useEffect(() => {
    onCaptureReady?.(capture);
    // Dev-only handle, alongside `__map`, so a capture can be run and
    // inspected from the console without going through the button.
    if (import.meta.env.DEV) {
      (window as unknown as { __capture?: typeof capture }).__capture = capture;
    }
    return () => onCaptureReady?.(null);
  }, [capture, onCaptureReady]);

  useEffect(() => {
    if (mapRef.current || !containerRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: BASE_STYLE,
      center: initialCamera?.center
        ? [initialCamera.center.lng, initialCamera.center.lat]
        : [INITIAL_VIEW.longitude, INITIAL_VIEW.latitude],
      zoom: initialCamera?.zoom ?? INITIAL_VIEW.zoom,
      pitch: initialCamera?.pitch ?? INITIAL_VIEW.pitch,
      bearing: initialCamera?.bearing ?? INITIAL_VIEW.bearing,
      attributionControl: { compact: true },
      // So the basemap half of a postcard survives to be read back. MapLibre 5
      // moved this out of the top level into `canvasContextAttributes`; passed
      // at the top level it is accepted and silently ignored, and the postcard
      // comes out as buildings floating on black.
      canvasContextAttributes: { preserveDrawingBuffer: true },
    });
    map.addControl(
      new maplibregl.NavigationControl({ visualizePitch: true }),
      "top-right",
    );
    const overlay = new MapboxOverlay({
      interleaved: false,
      layers: [],
      effects: [createBuildingLighting()],
    });
    map.addControl(overlay);
    map.on("load", () => onMapReady?.(map));
    map.on("click", (e: MapLayerMouseEvent) => {
      // Clicking an existing building selects it; only empty map triggers a
      // fresh footprint lookup. Without this, inspecting a building also fires
      // an Overpass query, and Overpass is the most fragile thing we depend on.
      const hit = overlay.pickObject({ x: e.point.x, y: e.point.y, radius: 4 });
      if (hit?.object) return;
      clickRef.current?.(e.lngLat.lat, e.lngLat.lng);
    });

    // --- drag a building to reposition it (step 09, without the sliders) ---
    const onMouseDown = (e: MapMouseEvent) => {
      const { enabled, selectedId: id } = dragRef.current;
      if (!enabled || !id) return;
      const hit = overlay.pickObject({ x: e.point.x, y: e.point.y, radius: 6 });
      const object = hit?.object as Generation | undefined;
      if (!object || object.id !== id) return;
      // Only the building being corrected is draggable; everything else keeps
      // its normal click-to-select behaviour.
      e.preventDefault();
      draggingRef.current = true;
      map.dragPan.disable();
      map.getCanvas().style.cursor = "grabbing";
    };
    const onMouseMove = (e: MapMouseEvent) => {
      if (!draggingRef.current) return;
      dragRef.current.onDragPlacement?.(e.lngLat.lat, e.lngLat.lng, false);
    };
    const onMouseUp = (e: MapMouseEvent) => {
      if (!draggingRef.current) return;
      draggingRef.current = false;
      map.dragPan.enable();
      map.getCanvas().style.cursor = "";
      dragRef.current.onDragPlacement?.(e.lngLat.lat, e.lngLat.lng, true);
    };
    map.on("mousedown", onMouseDown);
    map.on("mousemove", onMouseMove);
    map.on("mouseup", onMouseUp);
    // A pointer released outside the canvas must not leave the map stuck in a
    // drag with panning disabled.
    const onWindowUp = () => {
      if (!draggingRef.current) return;
      draggingRef.current = false;
      map.dragPan.enable();
      map.getCanvas().style.cursor = "";
      dragRef.current.onDragPlacement?.(map.getCenter().lat, map.getCenter().lng, true);
    };
    window.addEventListener("mouseup", onWindowUp);

    // Dev-only handle so the map can be poked from the console while debugging
    // tiles, sources and camera state.
    if (import.meta.env.DEV) {
      (window as unknown as { __map?: MapLibreMap }).__map = map;
    }

    mapRef.current = map;
    overlayRef.current = overlay;
    return () => {
      window.removeEventListener("mouseup", onWindowUp);
      overlay.finalize();
      map.remove();
      mapRef.current = null;
      overlayRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Cursor hint while dragging is armed.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    map.getCanvas().style.cursor = dragToPlace && selectedId ? "grab" : "";
  }, [dragToPlace, selectedId]);

  // Push layers whenever data or the live correction overrides change.
  useEffect(() => {
    const overlay = overlayRef.current;
    if (!overlay) return;
    const selected = rows.find((r) => r.id === selectedId) ?? null;
    // One mesh per address (the newest, or the selected one): two World States of the
    // same building sit at the same coordinate and would otherwise interpenetrate.
    const shown = visibleRows(rows, selectedId, pinnedIds);
    const layers = [
      buildRadiusLayer(
        propagate?.source ?? selected,
        propagate?.active ? propagate.radiusMeters : null,
      ),
      // Ground up: World State terrain, then contact shadows, then the buildings.
      ...buildTerrainLayers(shown, reveal),
      ...buildGroundShadowLayers(shown, reveal),
      ...buildScenegraphLayers(shown, { onClick: onSelect, roll, selectedId, overrides, reveal }),
      ...buildGhostLayers(ghost),
      buildConfidenceRingLayer(shown, { onClick: onSelect, selectedId, overrides, reveal }),
      buildPendingLayer(propagate?.pending),
      showLabels ? buildLabelLayer(shown) : null,
    ].filter(Boolean);
    overlay.setProps({ layers });
  }, [
    rows, selectedId, onSelect, roll, overrides, propagate,
    showLabels, pinnedIds, reveal, ghost,
  ]);

  // Satellite toggle: flip layer visibility rather than swapping the whole
  // style, so the deck.gl overlay and its loaded meshes survive the switch.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const apply = () => {
      if (!map.getLayer(OSM_LAYER_ID) || !map.getLayer(SATELLITE_LAYER_ID)) return;
      map.setLayoutProperty(
        SATELLITE_LAYER_ID,
        "visibility",
        satellite ? "visible" : "none",
      );
      map.setLayoutProperty(
        OSM_LAYER_ID,
        "visibility",
        satellite ? "none" : "visible",
      );
    };
    if (map.isStyleLoaded()) apply();
    else map.once("load", apply);
  }, [satellite]);

  // Fly to a building when it is selected from outside the map.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !selectedId) return;
    const row = rows.find((r) => r.id === selectedId);
    if (!row) return;
    map.easeTo({ center: [Number(row.lng), Number(row.lat)], duration: 700 });
  }, [selectedId, rows]);

  return <div className="map-root" ref={containerRef} />;
}
