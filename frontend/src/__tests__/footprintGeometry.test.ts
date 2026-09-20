import { describe, expect, it } from "vitest";
import {
  FALLBACK_FOOTPRINT,
  enclosingRadiusMeters,
  footprintCorners,
  footprintSize,
} from "../map/footprintGeometry";
import { haversineMeters } from "../lib/geo";
import type { Generation } from "../types/contract";

const row = (placement: Record<string, unknown> = {}): Generation =>
  ({
    id: "a",
    address: "Holden Hall, Blacksburg, VA",
    lat: 37.23019,
    lng: -80.42238,
    source_photo: null,
    artifact: null,
    mesh_url: null,
    world_state: "flooded",
    confidence_state: "auto-low",
    created_at: "2026-09-19T00:00:00Z",
    placement: {
      rotationDegrees: 0,
      scale: 1,
      position: [37.23019, -80.42238, 0],
      confidence: "auto-low",
      scoredRotationCandidates: [],
      footprintWidthMeters: 69.29,
      footprintDepthMeters: 61.85,
      ...placement,
    },
  }) as unknown as Generation;

describe("footprintSize", () => {
  it("uses the footprint step 08 carried through", () => {
    expect(footprintSize(row())).toEqual([69.29, 61.85]);
  });

  it("falls back when a row predates the footprint being stored", () => {
    expect(
      footprintSize(row({ footprintWidthMeters: null, footprintDepthMeters: null })),
    ).toEqual(FALLBACK_FOOTPRINT);
  });

  it("rejects nonsense rather than drawing a zero-size building", () => {
    expect(footprintSize(row({ footprintWidthMeters: 0 }))).toEqual(FALLBACK_FOOTPRINT);
    expect(footprintSize(row({ footprintDepthMeters: -5 }))).toEqual(FALLBACK_FOOTPRINT);
  });
});

describe("enclosingRadiusMeters", () => {
  it("encloses the whole building", () => {
    // Must clear the half-diagonal or the ring cuts through the corners.
    const [w, d] = footprintSize(row());
    expect(enclosingRadiusMeters(row())).toBeGreaterThan(0.5 * Math.hypot(w, d));
  });

  it("scales with the building instead of being fixed", () => {
    const small = enclosingRadiusMeters(
      row({ footprintWidthMeters: 9, footprintDepthMeters: 9 }),
    );
    const large = enclosingRadiusMeters(
      row({ footprintWidthMeters: 130, footprintDepthMeters: 42 }),
    );
    expect(large).toBeGreaterThan(small * 5);
  });
});

describe("footprintCorners", () => {
  it("returns four [lng, lat] corners", () => {
    const c = footprintCorners(row());
    expect(c).toHaveLength(4);
    for (const [lng, lat] of c) {
      expect(lng).toBeCloseTo(-80.42, 1);
      expect(lat).toBeCloseTo(37.23, 1);
    }
  });

  it("produces a rectangle of the footprint's real metre dimensions", () => {
    const [a, b, , d] = footprintCorners(row());
    const side1 = haversineMeters(a[1], a[0], b[1], b[0]);
    const side2 = haversineMeters(a[1], a[0], d[1], d[0]);
    const sides = [side1, side2].sort((x, y) => x - y);
    expect(sides[0]).toBeCloseTo(61.85, 0);
    expect(sides[1]).toBeCloseTo(69.29, 0);
  });

  it("rotates with the building's yaw", () => {
    const flat = footprintCorners(row({ rotationDegrees: 0 }));
    const turned = footprintCorners(row({ rotationDegrees: 45 }));
    // A rotated rectangle puts its corners somewhere else entirely.
    expect(turned[0][0]).not.toBeCloseTo(flat[0][0], 5);
  });

  it("a square footprint is unchanged by a 90 degree turn", () => {
    const sq = { footprintWidthMeters: 40, footprintDepthMeters: 40 };
    const a = footprintCorners(row({ ...sq, rotationDegrees: 0 }));
    const b = footprintCorners(row({ ...sq, rotationDegrees: 90 }));
    const setOf = (c: [number, number][]) =>
      c.map(([x, y]) => `${x.toFixed(6)},${y.toFixed(6)}`).sort();
    expect(setOf(b)).toEqual(setOf(a));
  });

  it("inflates about the centre for the soft shadow edge", () => {
    const tight = footprintCorners(row(), 1);
    const wide = footprintCorners(row(), 1.5);
    const span = (c: [number, number][]) => haversineMeters(c[0][1], c[0][0], c[2][1], c[2][0]);
    expect(span(wide)).toBeCloseTo(span(tight) * 1.5, 0);
  });
});
