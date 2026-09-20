import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import type { Map as MapLibreMap, MapLayerMouseEvent } from "maplibre-gl";
import { MapboxOverlay } from "@deck.gl/mapbox";
import "maplibre-gl/dist/maplibre-gl.css";

import {
  BASE_STYLE,
  INITIAL_VIEW,
  OSM_LAYER_ID,
  SATELLITE_LAYER_ID,
} from "./basemap";
import {
  buildConfidenceRingLayer,
  buildLabelLayer,
  buildPendingLayer,
  buildRadiusLayer,
  buildScenegraphLayers,
  visibleRows,
} from "./layers";
import type { Generation, PlacementOverrides } from "../types/contract";

export interface PropagateState {
  active: boolean;
  source: Generation;
  radiusMeters: number;
  revealed: Generation[];
  pending: { lat: number; lng: number; address?: string | null }[];
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
  onMapReady?: (map: MapLibreMap) => void;
  /** Clicking empty map is the step 01 "click the map instead of typing" path. */
  onMapClick?: (lat: number, lng: number) => void;
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
  onMapReady,
  onMapClick,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const overlayRef = useRef<MapboxOverlay | null>(null);
  // Kept in a ref so the map is created exactly once, never torn down on a
  // parent re-render just because a handler identity changed.
  const clickRef = useRef(onMapClick);
  clickRef.current = onMapClick;

  useEffect(() => {
    if (mapRef.current || !containerRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: BASE_STYLE,
      center: [INITIAL_VIEW.longitude, INITIAL_VIEW.latitude],
      zoom: INITIAL_VIEW.zoom,
      pitch: INITIAL_VIEW.pitch,
      bearing: INITIAL_VIEW.bearing,
      attributionControl: { compact: true },
    });
    map.addControl(
      new maplibregl.NavigationControl({ visualizePitch: true }),
      "top-right",
    );
    const overlay = new MapboxOverlay({ interleaved: false, layers: [] });
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

    // Dev-only handle so the map can be poked from the console while debugging
    // tiles, sources and camera state.
    if (import.meta.env.DEV) {
      (window as unknown as { __map?: MapLibreMap }).__map = map;
    }

    mapRef.current = map;
    overlayRef.current = overlay;
    return () => {
      overlay.finalize();
      map.remove();
      mapRef.current = null;
      overlayRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Push layers whenever data or the live correction overrides change.
  useEffect(() => {
    const overlay = overlayRef.current;
    if (!overlay) return;
    const selected = rows.find((r) => r.id === selectedId) ?? null;
    // One mesh per address (the newest, or the selected one): two World States of the
    // same building sit at the same coordinate and would otherwise interpenetrate.
    const shown = visibleRows(rows, selectedId);
    const layers = [
      buildRadiusLayer(
        propagate?.source ?? selected,
        propagate?.active ? propagate.radiusMeters : null,
      ),
      ...buildScenegraphLayers(shown, { onClick: onSelect, roll, selectedId, overrides }),
      buildConfidenceRingLayer(shown, { onClick: onSelect, selectedId, overrides }),
      buildPendingLayer(propagate?.pending),
      showLabels ? buildLabelLayer(shown) : null,
    ].filter(Boolean);
    overlay.setProps({ layers });
  }, [rows, selectedId, onSelect, roll, overrides, propagate, showLabels]);

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
