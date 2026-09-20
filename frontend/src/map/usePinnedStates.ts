import { useCallback, useEffect, useMemo, useState } from "react";
import type { Generation } from "../types/contract";

/**
 * Which World State the user chose to leave on each building.
 *
 * Picking a state from a building's history used to last only as long as the
 * panel stayed open: the map fell back to the newest row per address, so
 * closing the panel quietly undid the choice. A pin is that choice made
 * durable — keyed by address, storing the row id to show.
 *
 * Kept in localStorage, which is per-browser and never reaches the backend or
 * another viewer. That is the right scope for "how I want the map to look",
 * and it means a reload during a demo does not lose the arrangement. Every
 * access is guarded: storage can be unavailable or throw in a private window,
 * and the map has to work regardless.
 */
const STORAGE_KEY = "scorched-nebraska:pinned-world-states";

type PinMap = Record<string, string>;

function readStored(): PinMap {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    return Object.fromEntries(
      Object.entries(parsed as Record<string, unknown>).filter(
        ([k, v]) => typeof k === "string" && typeof v === "string",
      ),
    ) as PinMap;
  } catch {
    return {};
  }
}

function writeStored(pins: PinMap): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(pins));
  } catch {
    // Private window, blocked storage, quota — the map still works without it.
  }
}

export function usePinnedStates(rows: Generation[]) {
  const [pins, setPins] = useState<PinMap>(() => readStored());

  useEffect(() => {
    writeStored(pins);
  }, [pins]);

  // Drop pins whose row no longer exists — a reset store would otherwise leave
  // an address permanently pointing at a row that is never coming back.
  useEffect(() => {
    if (!rows.length) return;
    const live = new Set(rows.map((r) => r.id));
    setPins((prev) => {
      const kept = Object.fromEntries(
        Object.entries(prev).filter(([, id]) => live.has(id)),
      );
      return Object.keys(kept).length === Object.keys(prev).length ? prev : kept;
    });
  }, [rows]);

  const pinnedIds = useMemo(() => new Set(Object.values(pins)), [pins]);

  /** Leave this row's World State showing on its building. */
  const pin = useCallback((row: Generation) => {
    setPins((prev) => ({ ...prev, [row.address || row.id]: row.id }));
  }, []);

  /** Hand the address back to "whatever was generated last". */
  const unpin = useCallback((row: Generation) => {
    setPins((prev) => {
      const key = row.address || row.id;
      if (!(key in prev)) return prev;
      const next = { ...prev };
      delete next[key];
      return next;
    });
  }, []);

  const isPinned = useCallback((row: Generation) => pinnedIds.has(row.id), [pinnedIds]);

  return { pinnedIds, pin, unpin, isPinned };
}
