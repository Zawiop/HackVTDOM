import { useCallback, useEffect, useRef, useState } from "react";
import type { Map as MapLibreMap } from "maplibre-gl";
import type { Generation } from "../types/contract";

/**
 * Fly the camera through every building, unattended.
 *
 * The pitch has a hard problem: the world is the point, and the world takes
 * thirty seconds of clicking to show. This walks it on its own while whoever
 * is presenting talks, and stops the moment they touch the map — a tour that
 * fights the user for the camera is worse than no tour.
 */

export const DWELL_MS = 4200;
const FLIGHT_MS = 1600;

export interface TourOptions {
  onArrive?: (row: Generation) => void;
  onStop?: () => void;
  dwellMs?: number;
}

export function useTour(
  map: MapLibreMap | null,
  stops: Generation[],
  { onArrive, onStop, dwellMs = DWELL_MS }: TourOptions = {},
) {
  const [running, setRunning] = useState(false);
  const [index, setIndex] = useState(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Held in refs so restarting the timer never depends on a changed callback
  // identity — otherwise every parent render would reset the dwell.
  const stopsRef = useRef(stops);
  stopsRef.current = stops;
  const arriveRef = useRef(onArrive);
  arriveRef.current = onArrive;

  const clear = useCallback(() => {
    if (timer.current) {
      clearTimeout(timer.current);
      timer.current = null;
    }
  }, []);

  const stop = useCallback(() => {
    clear();
    setRunning(false);
    onStop?.();
  }, [clear, onStop]);

  const goTo = useCallback(
    (i: number) => {
      const list = stopsRef.current;
      if (!list.length) return;
      const wrapped = ((i % list.length) + list.length) % list.length;
      const row = list[wrapped];
      setIndex(wrapped);
      arriveRef.current?.(row);
      map?.flyTo({
        center: [Number(row.lng), Number(row.lat)],
        zoom: 17.6,
        pitch: 55,
        // A slow turn between stops keeps the buildings reading as solid
        // rather than as flat cards that snap to a new angle.
        bearing: (wrapped * 47) % 360,
        duration: FLIGHT_MS,
        essential: true,
      });
    },
    [map],
  );

  const start = useCallback(() => {
    if (!stopsRef.current.length) return;
    setRunning(true);
    goTo(0);
  }, [goTo]);

  const toggle = useCallback(() => (running ? stop() : start()), [running, start, stop]);

  // Advance on a dwell timer while running.
  useEffect(() => {
    if (!running) return;
    clear();
    timer.current = setTimeout(() => goTo(index + 1), dwellMs);
    return clear;
  }, [running, index, dwellMs, goTo, clear]);

  // Any real interaction hands the camera back. `movestart` alone would fire
  // on the tour's own flights, so this listens for the input events instead.
  useEffect(() => {
    if (!map || !running) return;
    const handOver = () => stop();
    const events = ["dragstart", "mousedown", "wheel", "touchstart"] as const;
    for (const e of events) map.on(e, handOver);
    return () => {
      for (const e of events) map.off(e, handOver);
    };
  }, [map, running, stop]);

  useEffect(() => clear, [clear]);

  return {
    running,
    index,
    total: stops.length,
    current: stops[index] ?? null,
    start,
    stop,
    toggle,
    next: useCallback(() => goTo(index + 1), [goTo, index]),
    previous: useCallback(() => goTo(index - 1), [goTo, index]),
  };
}
