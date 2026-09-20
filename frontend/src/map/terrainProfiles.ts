import type { Rgba } from "./terrainNoise";

/**
 * What each World State does to the ground.
 *
 * One profile per state, all five implemented. The numbers are read by
 * `terrain.ts`, which turns them into elevated cells and scattered features —
 * nothing here draws anything itself, so a state can be retuned without
 * touching the geometry code.
 */

export type FeatureKind = "tree" | "dune" | "flotsam" | "spire" | "stump";

export interface TerrainProfile {
  /** Ground closest to the building, where the state is strongest. */
  core: Rgba;
  /** Mid apron. */
  mid: Rgba;
  /** Outer falloff into the ordinary map. */
  edge: Rgba;
  /** Lifted ground: ridges, crests, canopy floor. */
  high: Rgba;
  /** Sunk ground: hollows, channels, water depth. */
  low: Rgba;

  /** Metres the surface sits above map ground at the patch centre. */
  baseElevation: number;
  /** Metres of peak-to-trough relief across the patch. */
  relief: number;
  /** Larger = broader, smoother landforms; smaller = choppier. */
  featureScale: number;
  /** How far the ground reaches, as a multiple of the building's half-diagonal. */
  reach: number;

  feature: FeatureKind;
  /** Roughly how many features across the whole patch. */
  featureCount: number;
  featureHeight: [number, number];
  featureRadius: [number, number];
  featureColor: Rgba;
  featureAccent: Rgba;
}

export const PROFILES: Record<string, TerrainProfile> = {
  // Blown sand and ash. Dunes bank up, hollows scour out, charred stumps.
  scorched: {
    core: [150, 96, 42, 225],
    mid: [186, 134, 74, 186],
    edge: [206, 170, 118, 92],
    high: [214, 168, 104, 225],
    low: [104, 64, 30, 230],
    baseElevation: 0.4,
    relief: 9,
    featureScale: 46,
    reach: 2.6,
    feature: "stump",
    featureCount: 26,
    featureHeight: [3, 9],
    featureRadius: [0.6, 1.6],
    featureColor: [58, 40, 26, 245],
    featureAccent: [96, 70, 44, 235],
  },

  // Standing water. A near-flat surface with a little swell, wreckage afloat.
  flooded: {
    core: [24, 68, 78, 214],
    mid: [38, 96, 100, 170],
    edge: [80, 134, 128, 96],
    high: [72, 128, 126, 200],
    low: [12, 40, 50, 235],
    baseElevation: 1.6,
    relief: 1.5,
    featureScale: 70,
    reach: 2.8,
    feature: "flotsam",
    featureCount: 30,
    featureHeight: [0.4, 1.4],
    featureRadius: [1.2, 3.4],
    featureColor: [46, 40, 34, 235],
    featureAccent: [88, 108, 96, 220],
  },

  // Forest taking the block back. Rolling undergrowth, a real canopy.
  reclaimed: {
    core: [52, 84, 40, 220],
    mid: [84, 118, 56, 180],
    edge: [126, 150, 92, 92],
    high: [110, 142, 68, 220],
    low: [34, 56, 28, 230],
    baseElevation: 0.3,
    relief: 5,
    featureScale: 40,
    reach: 2.7,
    feature: "tree",
    featureCount: 40,
    featureHeight: [8, 21],
    featureRadius: [2.6, 6.2],
    featureColor: [46, 84, 38, 240],
    featureAccent: [74, 116, 50, 235],
  },

  // Swallowed. The deepest relief of the five — dunes climb the walls.
  buried: {
    core: [178, 148, 100, 228],
    mid: [202, 178, 134, 190],
    edge: [220, 202, 168, 98],
    high: [228, 206, 162, 230],
    low: [140, 112, 72, 232],
    baseElevation: 1.0,
    relief: 14,
    featureScale: 62,
    reach: 3.0,
    feature: "dune",
    featureCount: 16,
    featureHeight: [4, 13],
    featureRadius: [7, 18],
    featureColor: [212, 190, 148, 225],
    featureAccent: [186, 160, 116, 220],
  },

  // Ash-locked and still. Flat, pale, with mineral spires standing up out of it.
  petrified: {
    core: [118, 116, 112, 220],
    mid: [146, 144, 140, 178],
    edge: [174, 172, 168, 90],
    high: [166, 164, 158, 222],
    low: [86, 86, 84, 232],
    baseElevation: 0.5,
    relief: 4,
    featureScale: 52,
    reach: 2.5,
    feature: "spire",
    featureCount: 22,
    featureHeight: [5, 16],
    featureRadius: [1.0, 2.8],
    featureColor: [98, 98, 96, 242],
    featureAccent: [132, 132, 128, 232],
  },
};

/** Used when a row has no World State yet — visible, but clearly inert. */
export const NEUTRAL: TerrainProfile = {
  core: [116, 114, 110, 150],
  mid: [142, 140, 136, 108],
  edge: [168, 166, 162, 58],
  high: [154, 152, 148, 150],
  low: [92, 90, 88, 160],
  baseElevation: 0.2,
  relief: 2,
  featureScale: 50,
  reach: 2.2,
  feature: "dune",
  featureCount: 8,
  featureHeight: [1, 3],
  featureRadius: [4, 9],
  featureColor: [150, 148, 144, 180],
  featureAccent: [128, 126, 122, 175],
};

export function profileFor(state: string | null | undefined): TerrainProfile {
  return (state && PROFILES[state]) || NEUTRAL;
}
