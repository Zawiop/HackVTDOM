import { metersPerDegree } from "../lib/geo";
import type { Generation, WorldState } from "../types/contract";
import { footprintSize } from "./footprintGeometry";

/**
 * The ground a building stands in, coloured by its World State.
 *
 * Buildings dropped onto raster street tiles read as models pasted on a map.
 * In the reference art the ground itself carries the state — a flooded block
 * sits in standing water, a scorched one in blown sand, a reclaimed one in
 * overgrowth. This draws that: concentric organic patches around each
 * building, fading out into the untouched basemap.
 *
 * Every patch is deterministic in the row id, so a building's ground looks the
 * same on every load and between machines — nothing here re-randomises on a
 * re-render, which would shimmer while panning.
 */

export type Rgba = [number, number, number, number];

interface StatePalette {
  /** Ground closest to the building, where the state is strongest. */
  core: Rgba;
  /** Mid apron. */
  mid: Rgba;
  /** Outer falloff into the ordinary map. */
  edge: Rgba;
  /** Scatter dots: debris, vegetation, floating wreckage. */
  fleck: Rgba;
}

/**
 * Sampled off the Scorched Nebraska reference art rather than invented:
 * ochre dust, still teal water, moss green, pale dune, grey ash.
 */
const PALETTES: Record<string, StatePalette> = {
  scorched: {
    core: [168, 112, 48, 210],
    mid: [196, 146, 82, 150],
    edge: [214, 178, 126, 78],
    fleck: [92, 60, 30, 170],
  },
  flooded: {
    core: [28, 74, 82, 212],
    mid: [44, 104, 104, 156],
    edge: [86, 140, 132, 82],
    fleck: [16, 44, 50, 165],
  },
  reclaimed: {
    core: [58, 92, 44, 208],
    mid: [92, 126, 60, 150],
    edge: [136, 158, 96, 78],
    fleck: [34, 58, 28, 170],
  },
  buried: {
    core: [186, 158, 110, 214],
    mid: [206, 182, 140, 156],
    edge: [222, 205, 172, 84],
    fleck: [150, 122, 82, 160],
  },
  petrified: {
    core: [126, 124, 120, 208],
    mid: [152, 150, 146, 148],
    edge: [178, 176, 172, 76],
    fleck: [92, 90, 88, 165],
  },
};

const NEUTRAL: StatePalette = {
  core: [120, 118, 112, 150],
  mid: [146, 144, 138, 104],
  edge: [170, 168, 162, 56],
  fleck: [96, 94, 90, 130],
};

export function paletteFor(state: WorldState | null | undefined): StatePalette {
  return (state && PALETTES[state]) || NEUTRAL;
}

/** Deterministic 0..1 sequence from a string — same ground on every load. */
function seeded(seed: string): () => number {
  let h = 2166136261;
  for (let i = 0; i < seed.length; i++) {
    h ^= seed.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return () => {
    h ^= h << 13;
    h ^= h >>> 17;
    h ^= h << 5;
    return ((h >>> 0) % 100000) / 100000;
  };
}

/**
 * An organic closed ring around the building.
 *
 * A plain circle reads as a UI annotation, so each vertex radius is jittered
 * and the jitter is smoothed between neighbours to avoid a spiky star.
 */
function blob(
  lat: number,
  lng: number,
  radiusM: number,
  rand: () => number,
  points = 30,
  jitter = 0.24,
): [number, number][] {
  const [mLat, mLng] = metersPerDegree(lat);
  const raw = Array.from({ length: points }, () => 1 + (rand() - 0.5) * 2 * jitter);
  return raw.map((_, i) => {
    const prev = raw[(i - 1 + points) % points];
    const next = raw[(i + 1) % points];
    const smooth = (prev + raw[i] * 2 + next) / 4;
    const r = radiusM * smooth;
    const a = (i / points) * Math.PI * 2;
    return [lng + (Math.cos(a) * r) / mLng, lat + (Math.sin(a) * r) / mLat];
  });
}

export interface TerrainRing {
  id: string;
  polygon: [number, number][];
  color: Rgba;
}

/** Outer-to-inner rings, so later rings paint over earlier ones. */
export function terrainRings(row: Generation): TerrainRing[] {
  const lat = Number(row.placement?.position?.[0] ?? row.lat);
  const lng = Number(row.placement?.position?.[1] ?? row.lng);
  const [w, d] = footprintSize(row);
  const base = 0.5 * Math.hypot(w, d);
  const p = paletteFor(row.world_state);

  return [
    { id: `${row.id}-edge`, radius: base * 2.5, color: p.edge, jitter: 0.3 },
    { id: `${row.id}-mid`, radius: base * 1.75, color: p.mid, jitter: 0.24 },
    { id: `${row.id}-core`, radius: base * 1.22, color: p.core, jitter: 0.16 },
  ].map(({ id, radius, color, jitter }) => ({
    id,
    // Re-seed per ring so the three outlines do not sit concentric and obvious.
    polygon: blob(lat, lng, radius, seeded(id), 30, jitter),
    color,
  }));
}

export interface TerrainFleck {
  position: [number, number];
  radius: number;
  color: Rgba;
}

/** Debris and growth scattered through the patch, thickest near the building. */
export function terrainFlecks(row: Generation, count = 26): TerrainFleck[] {
  const lat = Number(row.placement?.position?.[0] ?? row.lat);
  const lng = Number(row.placement?.position?.[1] ?? row.lng);
  const [w, d] = footprintSize(row);
  const base = 0.5 * Math.hypot(w, d);
  const { fleck } = paletteFor(row.world_state);
  const [mLat, mLng] = metersPerDegree(lat);
  const rand = seeded(`${row.id}-fleck`);

  return Array.from({ length: count }, () => {
    const a = rand() * Math.PI * 2;
    // sqrt keeps them from clumping in the middle; 0.55 clears the building.
    const r = base * (0.55 + Math.sqrt(rand()) * 1.75);
    return {
      position: [lng + (Math.cos(a) * r) / mLng, lat + (Math.sin(a) * r) / mLat],
      radius: base * (0.03 + rand() * 0.07),
      color: fleck,
    } as TerrainFleck;
  });
}
