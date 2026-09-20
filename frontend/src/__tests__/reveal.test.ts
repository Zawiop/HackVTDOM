import { describe, expect, it } from "vitest";
import {
  buildGhostLayers,
  buildGroundShadowLayers,
  buildScenegraphLayers,
  buildTerrainLayers,
  clampReveal,
} from "../map/layers";
import type { Generation } from "../types/contract";

const row = (over: Partial<Generation> = {}): Generation =>
  ({
    id: "a",
    address: "Burruss Hall, Blacksburg, VA",
    lat: 37.2287,
    lng: -80.4229,
    source_photo: null,
    artifact: null,
    mesh_url: "/placeholder.glb",
    world_state: "flooded",
    confidence_state: "auto-high",
    created_at: "2026-09-19T00:00:00Z",
    placement: {
      rotationDegrees: 0, scale: 1, position: [37.2287, -80.4229, 0],
      footprintWidthMeters: 100, footprintDepthMeters: 70,
    },
    ...over,
  }) as Generation;

describe("clampReveal", () => {
  it("holds the 0..1 range", () => {
    expect(clampReveal(0.5)).toBe(0.5);
    expect(clampReveal(-2)).toBe(0);
    expect(clampReveal(9)).toBe(1);
  });

  it("reads a malformed URL parameter as fully revealed", () => {
    // `?rv=banana` should show the world, not hide it — a broken link that
    // renders an empty map looks like a broken app.
    expect(clampReveal(NaN)).toBe(1);
    expect(clampReveal(null)).toBe(1);
    expect(clampReveal(undefined)).toBe(1);
  });
});

describe("the before/after reveal", () => {
  const rows = [row()];

  it("fades buildings, terrain and shadows together", () => {
    expect(buildScenegraphLayers(rows, { reveal: 0.5 })[0].props.opacity).toBe(0.5);
    for (const layer of buildTerrainLayers(rows, 0.5)) {
      expect(layer.props.opacity).toBe(0.5);
    }
    for (const layer of buildGroundShadowLayers(rows, 0.5)) {
      expect(layer.props.opacity).toBe(0.5);
    }
  });

  it("builds nothing at all at zero, rather than invisible layers", () => {
    expect(buildScenegraphLayers(rows, { reveal: 0 })).toHaveLength(0);
    expect(buildTerrainLayers(rows, 0)).toHaveLength(0);
    expect(buildGroundShadowLayers(rows, 0)).toHaveLength(0);
  });

  it("is fully revealed by default, so nothing has to opt in", () => {
    expect(buildScenegraphLayers(rows)[0].props.opacity).toBe(1);
    expect(buildTerrainLayers(rows)[0].props.opacity).toBe(1);
  });

  it("stops a half-faded building swallowing clicks meant for the map", () => {
    expect(buildScenegraphLayers(rows, { reveal: 1 })[0].props.pickable).toBe(true);
    expect(buildScenegraphLayers(rows, { reveal: 0.2 })[0].props.pickable).toBe(false);
  });
});

describe("the ghost block shown while a building generates", () => {
  it("is nothing when nothing is generating", () => {
    expect(buildGhostLayers(null)).toHaveLength(0);
    expect(buildGhostLayers(undefined)).toHaveLength(0);
  });

  it("sits at the real footprint, so the wait happens where the result will", () => {
    const layers = buildGhostLayers({
      lat: 37.2287, lng: -80.4229,
      widthMeters: 100, depthMeters: 70, rotationDegrees: 137,
    });
    expect(layers.length).toBeGreaterThan(0);
    const corners = layers[0].props.getPolygon(layers[0].props.data[0]);
    expect(corners).toHaveLength(4);
    // A 100 x 70 m building spans well over a hundred metres corner to corner,
    // which at this latitude is a bit over a thousandth of a degree.
    const lngs = corners.map((c: [number, number]) => c[0]);
    expect(Math.max(...lngs) - Math.min(...lngs)).toBeGreaterThan(0.0005);
  });

  it("still draws a block when the footprint size is unknown", () => {
    // A map-click with no matched OSM building has no dimensions; a ghost of
    // nothing would be worse than a ghost of a guess.
    const layers = buildGhostLayers({ lat: 37.2287, lng: -80.4229 });
    expect(layers[0].props.getPolygon(layers[0].props.data[0])).toHaveLength(4);
    expect(layers[0].props.getElevation).toBeGreaterThan(0);
  });
});
