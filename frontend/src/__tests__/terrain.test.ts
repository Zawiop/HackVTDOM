import { describe, expect, it } from "vitest";
import { paletteFor, terrainFlecks, terrainRings } from "../map/terrain";
import { haversineMeters } from "../lib/geo";
import type { Generation, WorldState } from "../types/contract";

const row = (over: Partial<Generation> = {}): Generation =>
  ({
    id: "row-1",
    address: "Burruss Hall, Blacksburg, VA",
    lat: 37.22906,
    lng: -80.42372,
    source_photo: null,
    artifact: null,
    mesh_url: null,
    world_state: "flooded",
    confidence_state: "auto-high",
    created_at: "2026-09-19T00:00:00Z",
    placement: {
      rotationDegrees: 137,
      scale: 1,
      position: [37.22906, -80.42372, 0],
      confidence: "auto-high",
      scoredRotationCandidates: [],
      footprintWidthMeters: 101.88,
      footprintDepthMeters: 70.79,
    },
    ...over,
  }) as unknown as Generation;

describe("paletteFor", () => {
  it("gives each World State its own ground", () => {
    const states: WorldState[] = [
      "scorched",
      "flooded",
      "reclaimed",
      "buried",
      "petrified",
    ];
    const cores = states.map((s) => paletteFor(s).core.join(","));
    expect(new Set(cores).size).toBe(states.length);
  });

  it("reads as water for flooded and as dust for scorched", () => {
    const [fr, fg, fb] = paletteFor("flooded").core;
    expect(fb).toBeGreaterThan(fr); // blue-leaning
    const [sr, , sb] = paletteFor("scorched").core;
    expect(sr).toBeGreaterThan(sb); // warm
  });

  it("falls back to neutral ground for an unknown or missing state", () => {
    expect(paletteFor(null)).toEqual(paletteFor(undefined));
    expect(paletteFor("nonsense" as WorldState).core).toEqual(paletteFor(null).core);
  });
});

describe("terrainRings", () => {
  it("returns outer-to-inner rings so later ones paint on top", () => {
    const rings = terrainRings(row());
    expect(rings).toHaveLength(3);
    const span = (r: (typeof rings)[number]) => {
      const lats = r.polygon.map(([, la]) => la);
      return Math.max(...lats) - Math.min(...lats);
    };
    expect(span(rings[0])).toBeGreaterThan(span(rings[1]));
    expect(span(rings[1])).toBeGreaterThan(span(rings[2]));
  });

  it("is deterministic in the row id — ground must not shimmer while panning", () => {
    expect(terrainRings(row())).toEqual(terrainRings(row()));
  });

  it("gives two different buildings different ground", () => {
    const a = terrainRings(row({ id: "row-1" }))[0].polygon;
    const b = terrainRings(row({ id: "row-2" }))[0].polygon;
    expect(a).not.toEqual(b);
  });

  it("is not a plain circle", () => {
    const [{ polygon }] = terrainRings(row());
    const c = row();
    const radii = polygon.map(([lng, lat]) =>
      haversineMeters(c.lat, c.lng, lat, lng),
    );
    const spread = (Math.max(...radii) - Math.min(...radii)) / Math.max(...radii);
    expect(spread).toBeGreaterThan(0.08);
  });

  it("scales with the building", () => {
    const small = terrainRings(
      row({
        id: "s",
        placement: { ...row().placement, footprintWidthMeters: 10, footprintDepthMeters: 10 },
      } as Partial<Generation>),
    );
    const big = terrainRings(row({ id: "s" }));
    const reach = (rings: typeof small) =>
      Math.max(...rings[0].polygon.map(([, la]) => Math.abs(la - 37.22906)));
    expect(reach(big)).toBeGreaterThan(reach(small) * 2);
  });
});

describe("terrainFlecks", () => {
  it("scatters debris without burying the building itself", () => {
    const flecks = terrainFlecks(row(), 40);
    expect(flecks).toHaveLength(40);
    const c = row();
    for (const f of flecks) {
      const dist = haversineMeters(c.lat, c.lng, f.position[1], f.position[0]);
      expect(dist).toBeGreaterThan(30); // clear of a 101x70 m footprint's core
    }
  });

  it("is deterministic per row", () => {
    expect(terrainFlecks(row())).toEqual(terrainFlecks(row()));
  });

  it("uses the World State's own debris colour", () => {
    expect(terrainFlecks(row({ world_state: "scorched" }))[0].color).toEqual(
      paletteFor("scorched").fleck,
    );
  });
});
