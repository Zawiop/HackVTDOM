import { describe, expect, it } from "vitest";
import { featurePolygon, profileFor, terrainCells, terrainFeatures } from "../map/terrain";
import { PROFILES } from "../map/terrainProfiles";
import { fractalNoise2D, mixColor, seededRandom, smoothstep } from "../map/terrainNoise";
import { haversineMeters } from "../lib/geo";
import type { Generation, WorldState } from "../types/contract";

const STATES: WorldState[] = ["scorched", "flooded", "reclaimed", "buried", "petrified"];

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

describe("profiles", () => {
  it("implements every World State", () => {
    for (const s of STATES) expect(PROFILES[s]).toBeDefined();
    expect(Object.keys(PROFILES)).toHaveLength(STATES.length);
  });

  it("gives each state its own ground colour and feature", () => {
    expect(new Set(STATES.map((s) => profileFor(s).core.join(",")))).toHaveProperty(
      "size",
      STATES.length,
    );
    expect(new Set(STATES.map((s) => profileFor(s).feature))).toHaveProperty(
      "size",
      STATES.length,
    );
  });

  it("reads as water for flooded and as dust for scorched", () => {
    const [fr, , fb] = profileFor("flooded").core;
    expect(fb).toBeGreaterThan(fr);
    const [sr, , sb] = profileFor("scorched").core;
    expect(sr).toBeGreaterThan(sb);
  });

  it("keeps water nearly flat and buries the deepest", () => {
    expect(profileFor("flooded").relief).toBeLessThan(profileFor("scorched").relief);
    expect(profileFor("buried").relief).toBeGreaterThan(profileFor("scorched").relief);
  });

  it("falls back to inert ground for an unknown state", () => {
    expect(profileFor(null)).toEqual(profileFor(undefined));
    expect(profileFor("nonsense").core).toEqual(profileFor(null).core);
  });
});

describe("noise", () => {
  it("is deterministic and bounded", () => {
    for (let i = 0; i < 40; i++) {
      const v = fractalNoise2D(i * 0.37, i * 0.11, 42);
      expect(v).toBeGreaterThanOrEqual(-1);
      expect(v).toBeLessThanOrEqual(1);
      expect(fractalNoise2D(i * 0.37, i * 0.11, 42)).toBe(v);
    }
  });

  it("actually varies across space — a constant would give flat ground", () => {
    const seen = new Set(
      Array.from({ length: 20 }, (_, i) => fractalNoise2D(i * 1.7, i * 2.3, 7).toFixed(3)),
    );
    expect(seen.size).toBeGreaterThan(10);
  });

  it("smoothstep clamps outside its edges", () => {
    expect(smoothstep(0, 10, -5)).toBe(0);
    expect(smoothstep(0, 10, 15)).toBe(1);
    expect(smoothstep(0, 10, 5)).toBeCloseTo(0.5, 5);
  });

  it("mixColor interpolates and stays in range", () => {
    expect(mixColor([0, 0, 0, 0], [255, 255, 255, 255], 0.5)).toEqual([128, 128, 128, 128]);
    expect(mixColor([0, 0, 0, 0], [255, 255, 255, 255], 5)).toEqual([255, 255, 255, 255]);
  });

  it("seededRandom repeats for the same seed and differs across seeds", () => {
    const a = seededRandom("x");
    const b = seededRandom("x");
    const c = seededRandom("y");
    const draw = (f: () => number) => Array.from({ length: 5 }, f);
    expect(draw(a)).toEqual(draw(b));
    expect(draw(seededRandom("x"))).not.toEqual(draw(c));
  });
});

describe("terrainCells", () => {
  it("covers the patch with elevated ground", () => {
    const cells = terrainCells(row());
    expect(cells.length).toBeGreaterThan(80);
    for (const c of cells) {
      expect(c.elevation).toBeGreaterThan(0);
      expect(c.polygon.length).toBeGreaterThanOrEqual(3);
    }
  });

  it("is deterministic — ground must not boil while panning", () => {
    expect(terrainCells(row())).toEqual(terrainCells(row()));
  });

  it("gives two buildings different ground", () => {
    expect(terrainCells(row({ id: "a" }))).not.toEqual(terrainCells(row({ id: "b" })));
  });

  it("is not a flat plane — relief is what makes it terrain", () => {
    const h = terrainCells(row({ world_state: "buried" })).map((c) => c.elevation);
    expect(Math.max(...h) - Math.min(...h)).toBeGreaterThan(2);
  });

  it("fades out rather than ending in a hard wall", () => {
    const c = row();
    const cells = terrainCells(c);
    const far = cells
      .map((cell) => {
        const [lng, lat] = cell.polygon[0];
        return { d: haversineMeters(c.lat, c.lng, lat, lng), a: cell.color[3] };
      })
      .sort((x, y) => y.d - x.d);
    // Outermost ground is more transparent than ground near the building.
    expect(far[0].a).toBeLessThan(far[far.length - 1].a);
  });

  it("scales with the building", () => {
    const small = row({
      id: "s",
      placement: { ...row().placement, footprintWidthMeters: 12, footprintDepthMeters: 10 },
    } as Partial<Generation>);
    const reach = (r: Generation) => {
      const cells = terrainCells(r);
      return Math.max(...cells.map((c) => Math.abs(c.polygon[0][1] - 37.22906)));
    };
    expect(reach(row())).toBeGreaterThan(reach(small) * 2);
  });
});

describe("terrainFeatures", () => {
  it("scatters the state's own feature without burying the building", () => {
    const c = row({ world_state: "reclaimed" });
    const features = terrainFeatures(c);
    expect(features.length).toBeGreaterThan(0);
    for (const f of features) {
      const dist = haversineMeters(c.lat, c.lng, f.position[1], f.position[0]);
      expect(dist).toBeGreaterThan(40); // clear of a 101x70 m footprint
      expect(f.elevation).toBeGreaterThan(0);
    }
  });

  it("gives trees a trunk as well as a canopy", () => {
    // Two parts per tree, and the canopy sits above the trunk base.
    const trees = terrainFeatures(row({ world_state: "reclaimed" }));
    const spires = terrainFeatures(row({ world_state: "petrified" }));
    expect(trees.length).toBeGreaterThan(spires.length);
    const raised = trees.filter((f) => f.position[2] > 0.5);
    expect(raised.length).toBeGreaterThan(0);
  });

  it("is deterministic per row", () => {
    expect(terrainFeatures(row())).toEqual(terrainFeatures(row()));
  });

  it("builds a closed ring of the requested side count", () => {
    const [f] = terrainFeatures(row({ world_state: "petrified" }));
    expect(featurePolygon(f)).toHaveLength(f.sides);
  });
});
