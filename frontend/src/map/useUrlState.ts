import { useCallback, useEffect, useRef } from "react";
import type { Map as MapLibreMap } from "maplibre-gl";

/**
 * The view lives in the URL.
 *
 * Two things were wrong without this. A reload dropped everything — camera,
 * which building was open, whether satellite was on — which during a demo
 * means one stray refresh costs you your shot. And there was no way to hand
 * somebody "look at *this*": the app had exactly one address, the root.
 *
 * Written with `replaceState`, not `pushState`: panning a map is not a
 * navigation, and filling someone's back button with camera positions makes
 * Back useless for leaving the page.
 */

export interface UrlState {
  buildingId: string | null;
  center: { lat: number; lng: number } | null;
  zoom: number | null;
  pitch: number | null;
  bearing: number | null;
  satellite: boolean | null;
  labels: boolean | null;
  reveal: number | null;
}

const EMPTY: UrlState = {
  buildingId: null, center: null, zoom: null, pitch: null,
  bearing: null, satellite: null, labels: null, reveal: null,
};

function num(value: string | null): number | null {
  if (value === null || value.trim() === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function bool(value: string | null): boolean | null {
  if (value === null) return null;
  return value === "1" || value === "true";
}

/** Parse a `?…` string. Exported for tests; malformed values read as absent. */
export function parseUrlState(search: string): UrlState {
  let params: URLSearchParams;
  try {
    params = new URLSearchParams(search);
  } catch {
    return EMPTY;
  }
  const centerRaw = params.get("c");
  let center: UrlState["center"] = null;
  if (centerRaw) {
    const [lat, lng] = centerRaw.split(",").map((p) => Number(p));
    // A half-parsed coordinate is worse than none: it would fly the map to the
    // Gulf of Guinea and look like a bug in placement.
    if (Number.isFinite(lat) && Number.isFinite(lng)) center = { lat, lng };
  }
  return {
    buildingId: params.get("b") || null,
    center,
    zoom: num(params.get("z")),
    pitch: num(params.get("p")),
    bearing: num(params.get("r")),
    satellite: bool(params.get("sat")),
    labels: bool(params.get("lbl")),
    reveal: num(params.get("rv")),
  };
}

/** The query string for a state. Defaults are left out to keep links readable. */
export function buildUrlSearch(state: UrlState): string {
  const params = new URLSearchParams();
  if (state.buildingId) params.set("b", state.buildingId);
  if (state.center) {
    params.set("c", `${state.center.lat.toFixed(6)},${state.center.lng.toFixed(6)}`);
  }
  if (state.zoom != null) params.set("z", state.zoom.toFixed(2));
  if (state.pitch) params.set("p", state.pitch.toFixed(0));
  if (state.bearing) params.set("r", state.bearing.toFixed(0));
  if (state.satellite) params.set("sat", "1");
  if (state.labels === false) params.set("lbl", "0");
  if (state.reveal != null && state.reveal < 1) params.set("rv", state.reveal.toFixed(2));
  const q = params.toString();
  return q ? `?${q}` : "";
}

/** Read once, at module scope, before anything has had a chance to overwrite it. */
export function readInitialUrlState(): UrlState {
  if (typeof window === "undefined") return EMPTY;
  return parseUrlState(window.location.search);
}

/**
 * Keep the address bar in step with the view.
 *
 * Camera writes are throttled behind an animation frame: MapLibre fires `move`
 * on every frame of a flight, and `replaceState` on each one is both wasted
 * work and enough to make some browsers complain about the rate.
 */
export function useUrlSync(
  map: MapLibreMap | null,
  state: Omit<UrlState, "center" | "zoom" | "pitch" | "bearing">,
) {
  const stateRef = useRef(state);
  stateRef.current = state;
  const frame = useRef<number | null>(null);

  const write = useCallback(() => {
    if (typeof window === "undefined") return;
    const m = map;
    const camera = m
      ? {
          center: { lat: m.getCenter().lat, lng: m.getCenter().lng },
          zoom: m.getZoom(),
          pitch: m.getPitch(),
          bearing: m.getBearing(),
        }
      : { center: null, zoom: null, pitch: null, bearing: null };
    const search = buildUrlSearch({ ...stateRef.current, ...camera });
    const next = `${window.location.pathname}${search}`;
    if (next === `${window.location.pathname}${window.location.search}`) return;
    try {
      window.history.replaceState(null, "", next);
    } catch {
      // Some embedded/sandboxed hosts refuse history writes. A URL that does
      // not update is a missing convenience, never a reason to break the app.
    }
  }, [map]);

  const schedule = useCallback(() => {
    if (typeof window === "undefined" || frame.current != null) return;
    frame.current = window.requestAnimationFrame(() => {
      frame.current = null;
      write();
    });
  }, [write]);

  // Non-camera state (selection, toggles) writes straight through — those
  // change at human speed, not at sixty hertz.
  useEffect(() => {
    write();
  }, [write, state.buildingId, state.satellite, state.labels, state.reveal]);

  useEffect(() => {
    if (!map) return;
    map.on("moveend", write);
    map.on("move", schedule);
    return () => {
      map.off("moveend", write);
      map.off("move", schedule);
      if (frame.current != null && typeof window !== "undefined") {
        window.cancelAnimationFrame(frame.current);
        frame.current = null;
      }
    };
  }, [map, write, schedule]);

  return { write };
}
