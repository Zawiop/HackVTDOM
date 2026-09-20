import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { usePinnedStates } from "../map/usePinnedStates";
import { visibleRows } from "../map/layers";
import type { Generation } from "../types/contract";

const KEY = "scorched-nebraska:pinned-world-states";

/**
 * This jsdom build gives us a `window` but no `localStorage` at all, so the
 * persistence tests install a minimal one. That gap is itself worth knowing:
 * the hook has to survive storage being entirely absent, not just throwing —
 * covered by the last two tests below.
 */
function installStorage(): Storage {
  const data = new Map<string, string>();
  const store = {
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, String(v)),
    removeItem: (k: string) => void data.delete(k),
    clear: () => data.clear(),
    key: (i: number) => [...data.keys()][i] ?? null,
    get length() {
      return data.size;
    },
  } as Storage;
  Object.defineProperty(window, "localStorage", {
    value: store,
    configurable: true,
    writable: true,
  });
  return store;
}

function removeStorage(): void {
  Object.defineProperty(window, "localStorage", {
    value: undefined,
    configurable: true,
    writable: true,
  });
}

const row = (id: string, world_state: string, created_at: string, address = "Burruss Hall"): Generation =>
  ({
    id,
    address,
    lat: 37.229,
    lng: -80.4237,
    source_photo: null,
    artifact: null,
    mesh_url: null,
    world_state,
    confidence_state: "auto-high",
    created_at,
    placement: {
      rotationDegrees: 0,
      scale: 1,
      position: [37.229, -80.4237, 0],
      confidence: "auto-high",
      scoredRotationCandidates: [],
    },
  }) as unknown as Generation;

const scorched = row("a", "scorched", "2026-09-19T01:00:00Z");
const flooded = row("b", "flooded", "2026-09-19T02:00:00Z"); // newer
const other = row("c", "reclaimed", "2026-09-19T03:00:00Z", "Norris Hall");

beforeEach(() => installStorage());
afterEach(() => vi.restoreAllMocks());

describe("visibleRows", () => {
  it("shows the newest state for an address by default", () => {
    const shown = visibleRows([scorched, flooded]);
    expect(shown).toHaveLength(1);
    expect(shown[0].world_state).toBe("flooded");
  });

  it("a pin beats the newest — this is what makes a choice stick", () => {
    const shown = visibleRows([scorched, flooded], null, new Set(["a"]));
    expect(shown[0].world_state).toBe("scorched");
  });

  it("the row being inspected beats the pin", () => {
    const shown = visibleRows([scorched, flooded], "b", new Set(["a"]));
    expect(shown[0].world_state).toBe("flooded");
  });

  it("still returns one row per address", () => {
    const shown = visibleRows([scorched, flooded, other], null, new Set(["a"]));
    expect(shown).toHaveLength(2);
    expect(new Set(shown.map((r) => r.address)).size).toBe(2);
  });

  it("a pin on one address does not disturb another", () => {
    const shown = visibleRows([scorched, flooded, other], null, new Set(["a"]));
    expect(shown.find((r) => r.address === "Norris Hall")?.world_state).toBe("reclaimed");
  });
});

describe("usePinnedStates", () => {
  it("pins by address and reports it", () => {
    const { result } = renderHook(() => usePinnedStates([scorched, flooded]));
    expect(result.current.isPinned(scorched)).toBe(false);
    act(() => result.current.pin(scorched));
    expect(result.current.isPinned(scorched)).toBe(true);
    expect(result.current.pinnedIds.has("a")).toBe(true);
  });

  it("one pin per address — choosing another state replaces it", () => {
    const { result } = renderHook(() => usePinnedStates([scorched, flooded]));
    act(() => result.current.pin(scorched));
    act(() => result.current.pin(flooded));
    expect(result.current.isPinned(scorched)).toBe(false);
    expect(result.current.isPinned(flooded)).toBe(true);
  });

  it("unpin hands the address back to the newest", () => {
    const { result } = renderHook(() => usePinnedStates([scorched, flooded]));
    act(() => result.current.pin(scorched));
    act(() => result.current.unpin(scorched));
    expect(result.current.pinnedIds.size).toBe(0);
  });

  it("survives a reload", () => {
    const first = renderHook(() => usePinnedStates([scorched, flooded]));
    act(() => first.result.current.pin(scorched));
    first.unmount();
    const second = renderHook(() => usePinnedStates([scorched, flooded]));
    expect(second.result.current.isPinned(scorched)).toBe(true);
  });

  it("drops pins whose row is gone, so a reset store cannot strand an address", () => {
    const { result, rerender } = renderHook(({ rows }) => usePinnedStates(rows), {
      initialProps: { rows: [scorched, flooded] },
    });
    act(() => result.current.pin(scorched));
    rerender({ rows: [flooded] }); // scorched no longer exists
    expect(result.current.pinnedIds.has("a")).toBe(false);
  });

  it("ignores junk in storage rather than throwing", () => {
    window.localStorage.setItem(KEY, "{not json");
    const { result } = renderHook(() => usePinnedStates([scorched]));
    expect(result.current.pinnedIds.size).toBe(0);
  });

  it("works when storage throws — a private window still gets a map", () => {
    const store = installStorage();
    vi.spyOn(store, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    vi.spyOn(store, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });
    const { result } = renderHook(() => usePinnedStates([scorched, flooded]));
    expect(() => act(() => result.current.pin(scorched))).not.toThrow();
    expect(result.current.isPinned(scorched)).toBe(true); // in-memory still works
  });

  it("works when storage is missing entirely", () => {
    removeStorage();
    const { result } = renderHook(() => usePinnedStates([scorched, flooded]));
    expect(() => act(() => result.current.pin(scorched))).not.toThrow();
    expect(result.current.isPinned(scorched)).toBe(true);
  });
});
