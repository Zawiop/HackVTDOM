import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderHook, act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import Landing from "../site/Landing";
import { navigate, pathForRoute, routeFromPath } from "../site/router";
import { useMyWorld } from "../world/useMyWorld";
import type { Generation } from "../types/contract";

describe("routeFromPath", () => {
  it("sends the root and anything unrecognised to the landing page", () => {
    for (const p of ["/", "", "/about", "/index.html", "/map-extra"]) {
      expect(routeFromPath(p)).toBe("home");
    }
  });

  it("recognises the map, with or without a trailing slash or base path", () => {
    for (const p of ["/map", "/map/", "/scorched-earth/map"]) {
      expect(routeFromPath(p)).toBe("map");
    }
  });

  it("round-trips", () => {
    expect(routeFromPath(pathForRoute("map"))).toBe("map");
    expect(routeFromPath(pathForRoute("home"))).toBe("home");
  });
});

describe("navigate", () => {
  beforeEach(() => window.history.replaceState({}, "", "/"));

  it("keeps the map's query state when moving between screens", () => {
    window.history.replaceState({}, "", "/map?c=37.2,-80.4&z=17");
    navigate("home");

    // The camera lives in the query string and is owned by useUrlState; going
    // home must not throw it away, or Back lands on a reset map.
    expect(window.location.pathname).toBe("/");
    expect(window.location.search).toBe("?c=37.2,-80.4&z=17");
  });

  it("pushes history so Back leaves the map", () => {
    const before = window.history.length;
    navigate("map");
    expect(window.location.pathname).toBe("/map");
    expect(window.history.length).toBeGreaterThanOrEqual(before);
  });

  it("does nothing when already there, so Back is not filled with duplicates", () => {
    navigate("map");
    const len = window.history.length;
    navigate("map");
    expect(window.history.length).toBe(len);
  });
});

describe("Landing", () => {
  beforeEach(() => window.history.replaceState({}, "", "/"));

  it("leads with what the product does", () => {
    render(<Landing />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(/scorched\s*earth/i);
  });

  it("offers a route into the map from the top, the middle and the end", async () => {
    render(<Landing />);
    const toMap = screen.getAllByRole("link", { name: /launch map|start exploring/i });
    expect(toMap.length).toBeGreaterThanOrEqual(3);

    await userEvent.click(toMap[0]);
    expect(window.location.pathname).toBe("/map");
  });

  it("frames itself as a companion to Scorched Nebraska, not a generic tool", () => {
    render(<Landing />);
    const section = document.getElementById("nebraska")!;
    expect(within(section).getByRole("heading", { level: 2 })).toHaveTextContent(/scorched nebraska/i);
    expect(within(section).getByText(/companion instrument/i)).toBeInTheDocument();
  });

  it("links out to Scorched Nebraska safely", () => {
    render(<Landing />);
    const link = screen.getByRole("link", { name: /visit scorched nebraska/i });

    expect(link).toHaveAttribute("href", "https://www.scorchednebraska.com/");
    // noopener stops the opened page reaching back through window.opener.
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
    expect(link).toHaveAttribute("rel", expect.stringContaining("noreferrer"));
  });

  it("names the three photo routes so the mobile choice is obvious", () => {
    render(<Landing />);
    const section = document.getElementById("capture")!;
    for (const label of ["Take Photo", "Choose Photo", "Upload File"]) {
      expect(within(section).getAllByText(label).length).toBeGreaterThan(0);
    }
  });

  it("carries the data attribution the licences require", () => {
    render(<Landing />);
    expect(screen.getByText(/OpenStreetMap contributors/i)).toBeInTheDocument();
    expect(screen.getByText(/Mapillary contributors/i)).toBeInTheDocument();
  });

  it("has no login, anywhere", () => {
    render(<Landing />);
    expect(
      screen.queryByRole("link", { name: /sign in|log in|register|create account/i }),
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: /sign in|log in|register|create account/i }),
    ).toBeNull();
    expect(document.querySelector('input[type="password"]')).toBeNull();
  });
});

// --- ownership ------------------------------------------------------------

const row = (id: string, address: string): Generation =>
  ({ id, address, lat: 0, lng: 0 }) as Generation;

describe("useMyWorld", () => {
  beforeEach(() => window.localStorage.clear());
  afterEach(() => vi.restoreAllMocks());

  it("claims nothing until something is generated", () => {
    const rows = [row("a", "Someone else's hall")];
    const { result } = renderHook(() => useMyWorld(rows));

    expect(result.current.mine).toEqual([]);
    expect(result.current.isMine(rows[0])).toBe(false);
  });

  it("owns what this browser made and nothing else", () => {
    const rows = [row("mine", "Mine Hall"), row("theirs", "Their Hall")];
    const { result, rerender } = renderHook(() => useMyWorld(rows));

    act(() => result.current.claim("mine"));
    rerender();

    expect(result.current.isMine(rows[0])).toBe(true);
    expect(result.current.isMine(rows[1])).toBe(false);
    expect(result.current.mineAddresses).toEqual(["Mine Hall"]);
  });

  it("survives a reload", () => {
    const rows = [row("mine", "Mine Hall")];
    const first = renderHook(() => useMyWorld(rows));
    act(() => first.result.current.claim("mine"));
    first.unmount();

    const second = renderHook(() => useMyWorld(rows));
    expect(second.result.current.isMine(rows[0])).toBe(true);
  });

  it("drops ids the server no longer has, so the count cannot go stale", () => {
    const { result, rerender } = renderHook(({ rows }) => useMyWorld(rows), {
      initialProps: { rows: [row("gone", "Gone Hall")] },
    });

    act(() => result.current.claim("gone"));
    rerender({ rows: [] });

    expect(result.current.mine).toEqual([]);
    expect(result.current.mineIds).toEqual([]);
  });

  it("keeps working when localStorage throws, as it does in a private window", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("QuotaExceededError");
    });
    const rows = [row("mine", "Mine Hall")];
    const { result, rerender } = renderHook(() => useMyWorld(rows));

    expect(() => act(() => result.current.claim("mine"))).not.toThrow();
    rerender();
    // In memory for this session even though it could not be persisted.
    expect(result.current.isMine(rows[0])).toBe(true);
  });

  it("ignores a corrupt stored value instead of crashing the map", () => {
    window.localStorage.setItem("scorched-earth:my-generations", "{not json");
    const { result } = renderHook(() => useMyWorld([row("a", "A")]));
    expect(result.current.mine).toEqual([]);
  });
});
