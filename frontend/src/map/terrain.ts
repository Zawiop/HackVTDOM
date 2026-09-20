import { metersPerDegree } from "../lib/geo";
import type { Generation } from "../types/contract";
import { footprintSize } from "./footprintGeometry";
import { profileFor } from "./terrainProfiles";
import type { FeatureKind, TerrainProfile } from "./terrainProfiles";
import {
  fractalNoise2D,
  hashString,
  mixColor,
  seededRandom,
  smoothstep,
  withAlpha,
} from "./terrainNoise";
import type { Rgba } from "./terrainNoise";

export { profileFor } from "./terrainProfiles";
export type { Rgba } from "./terrainNoise";

/**
 * The ground a building stands in, built as real terrain rather than a flat
 * colour wash: a field of extruded cells whose height comes from layered
 * noise, plus features that belong to that World State — trees for reclaimed,
 * dunes for buried, wreckage afloat on flooded, spires on petrified, burnt
 * stumps on scorched.
 *
 * Everything is a pure function of the row id, so the same building always
 * gets the same ground and nothing boils while the map pans.
 */

export interface TerrainCell {
  polygon: [number, number][];
  elevation: number;
  color: Rgba;
}

export interface TerrainFeature {
  position: [number, number, number];
  radius: number;
  elevation: number;
  color: Rgba;
  /** Cylinder-ish for trunks and spires, blockier for dunes and wreckage. */
  sides: number;
}

/** Half the building's diagonal — the unit every terrain distance is in. */
function buildingReach(row: Generation): number {
  const [w, d] = footprintSize(row);
  return 0.5 * Math.hypot(w, d);
}

function centreOf(row: Generation): [number, number] {
  return [
    Number(row.placement?.position?.[0] ?? row.lat),
    Number(row.placement?.position?.[1] ?? row.lng),
  ];
}

/**
 * Height field in metres at a local offset from the patch centre.
 *
 * Falls to zero at the patch edge so terrain meets the untouched basemap
 * without a visible step, and is damped right at the centre so the ground does
 * not erupt through the building standing on it.
 */
function heightAt(
  east: number,
  north: number,
  radius: number,
  profile: TerrainProfile,
  salt: number,
): { elevation: number; falloff: number; noise01: number } {
  const dist = Math.hypot(east, north);
  const falloff = 1 - smoothstep(radius * 0.55, radius, dist);
  const n = fractalNoise2D(east / profile.featureScale, north / profile.featureScale, salt);
  const noise01 = (n + 1) / 2;
  // Keep the middle calm: that is where the building is.
  const clearance = smoothstep(0, radius * 0.42, dist);
  const elevation =
    profile.baseElevation * falloff + profile.relief * noise01 * falloff * clearance;
  return { elevation, falloff, noise01 };
}

/** How strongly `row`'s ground reaches a point, 0 outside its patch. */
function influenceAt(row: Generation, lat: number, lng: number): number {
  const [cLat, cLng] = centreOf(row);
  const radius = buildingReach(row) * profileFor(row.world_state).reach;
  const [mLat, mLng] = metersPerDegree(cLat);
  const east = (lng - cLng) * mLng;
  const north = (lat - cLat) * mLat;
  return 1 - smoothstep(radius * 0.55, radius, Math.hypot(east, north));
}

/**
 * Ground for one building, blended against its neighbours.
 *
 * `neighbours` are other buildings whose patches can reach this one. Without
 * them, a flooded block next to a scorched block meets it at a hard seam —
 * whichever drew last simply wins. Weighting each cell's colour by how far
 * into each patch it sits makes the two states wash into each other the way
 * the reference art does.
 */
export function terrainCells(row: Generation, neighbours: Generation[] = []): TerrainCell[] {
  const profile = profileFor(row.world_state);
  const [lat, lng] = centreOf(row);
  const radius = buildingReach(row) * profile.reach;
  const [mLat, mLng] = metersPerDegree(lat);
  const salt = hashString(String(row.id));

  // Enough cells to read as ground, few enough to stay cheap across a district.
  const step = Math.max(6, radius / 10);
  const cells: TerrainCell[] = [];
  const jitter = seededRandom(`${row.id}-cells`);

  for (let gx = -radius; gx <= radius; gx += step) {
    for (let gy = -radius; gy <= radius; gy += step) {
      // A strict lattice reads as a checkerboard however it is coloured, so each
      // cell is displaced, resized and spun off the grid it came from.
      const east = gx + (jitter() - 0.5) * step * 0.85;
      const north = gy + (jitter() - 0.5) * step * 0.85;
      const size = step * (0.78 + jitter() * 0.5);
      const spin = jitter() * Math.PI * 2;
      if (Math.hypot(east, north) > radius) continue;
      const { elevation, falloff, noise01 } = heightAt(east, north, radius, profile, salt);
      if (falloff <= 0.01) continue;

      // Low ground reads as hollow and wet, high ground as crest and dry.
      const body = mixColor(profile.low, profile.core, smoothstep(0.15, 0.6, noise01));
      const lit = mixColor(body, profile.high, smoothstep(0.55, 1, noise01));
      let blended = mixColor(profile.edge, lit, falloff);

      // Wash into any neighbouring patch that reaches this cell.
      if (neighbours.length) {
        const cellLat = lat + north / mLat;
        const cellLng = lng + east / mLng;
        for (const other of neighbours) {
          if (other.world_state === row.world_state) continue;
          const theirs = influenceAt(other, cellLat, cellLng);
          if (theirs <= 0.01) continue;
          // Their share of this cell, relative to ours. Capped so a building
          // never loses its own ground entirely to a louder neighbour.
          const share = Math.min(0.5, (theirs / (theirs + falloff + 0.001)) * 0.8);
          blended = mixColor(blended, profileFor(other.world_state).core, share);
        }
      }

      // A rotated pentagon tiles far less obviously than an axis-aligned square.
      const sides = 5;
      const polygon = Array.from({ length: sides }, (_, i) => {
        const a = spin + (i / sides) * Math.PI * 2;
        return [
          lng + (east + Math.cos(a) * size) / mLng,
          lat + (north + Math.sin(a) * size) / mLat,
        ] as [number, number];
      });
      cells.push({
        polygon,
        elevation: Math.max(0.05, elevation),
        color: withAlpha(blended, 0.5 + falloff * 0.5),
      });
    }
  }
  return cells;
}

/** Trunk-and-canopy, spire, dune or wreckage, depending on the state. */
function featureParts(
  kind: FeatureKind,
  profile: TerrainProfile,
  base: [number, number, number],
  radius: number,
  height: number,
): TerrainFeature[] {
  const [lng, lat, z] = base;
  switch (kind) {
    case "tree":
      // A canopy alone floats; the trunk is what makes it read as a tree.
      return [
        {
          position: [lng, lat, z],
          radius: Math.max(0.5, radius * 0.18),
          elevation: height * 0.55,
          color: [54, 42, 30, 245],
          sides: 6,
        },
        {
          position: [lng, lat, z + height * 0.5],
          radius,
          elevation: height * 0.62,
          color: profile.featureColor,
          sides: 7,
        },
      ];
    case "spire":
      return [
        {
          position: [lng, lat, z],
          radius,
          elevation: height,
          color: profile.featureColor,
          sides: 5,
        },
      ];
    case "stump":
      return [
        {
          position: [lng, lat, z],
          radius,
          elevation: height,
          color: profile.featureColor,
          sides: 6,
        },
      ];
    case "dune":
      // Wide and shallow, so it banks rather than stands.
      return [
        {
          position: [lng, lat, z],
          radius,
          elevation: height,
          color: profile.featureColor,
          sides: 8,
        },
      ];
    case "flotsam":
    default:
      return [
        {
          position: [lng, lat, z],
          radius,
          elevation: height,
          color: profile.featureColor,
          sides: 4,
        },
      ];
  }
}

export function terrainFeatures(row: Generation): TerrainFeature[] {
  const profile = profileFor(row.world_state);
  const [lat, lng] = centreOf(row);
  const reach = buildingReach(row);
  const radius = reach * profile.reach;
  const [mLat, mLng] = metersPerDegree(lat);
  const salt = hashString(String(row.id));
  const rand = seededRandom(`${row.id}-features`);

  const out: TerrainFeature[] = [];
  for (let i = 0; i < profile.featureCount; i++) {
    const angle = rand() * Math.PI * 2;
    // sqrt spreads them evenly by area; the 0.85 floor keeps them off the walls.
    const dist = reach * (0.85 + Math.sqrt(rand()) * (profile.reach - 0.85));
    const east = Math.cos(angle) * dist;
    const north = Math.sin(angle) * dist;
    const { elevation, falloff } = heightAt(east, north, radius, profile, salt);
    if (falloff <= 0.12) continue; // nothing stranded out on the fade

    const [rMin, rMax] = profile.featureRadius;
    const [hMin, hMax] = profile.featureHeight;
    const size = rMin + rand() * (rMax - rMin);
    const height = (hMin + rand() * (hMax - hMin)) * (0.5 + falloff * 0.5);
    const tint = rand();

    const parts = featureParts(
      profile.feature,
      profile,
      [lng + east / mLng, lat + north / mLat, elevation],
      size,
      height,
    );
    for (const part of parts) {
      out.push({
        ...part,
        // Vary each one off the accent so a stand of trees is not one flat green.
        color: mixColor(part.color, profile.featureAccent, tint * 0.6),
      });
    }
  }
  return out;
}

/**
 * A feature as an extruded n-gon ring.
 *
 * ColumnLayer would be the obvious fit, but its `radius` is a layer-level prop
 * with no per-object accessor, and these need to vary size individually — one
 * layer per distinct radius is not a real option. Emitting the ring here keeps
 * features and ground cells on the same PolygonLayer machinery.
 */
export function featurePolygon(feature: TerrainFeature): [number, number, number][] {
  const [lng, lat, z] = feature.position;
  const [mLat, mLng] = metersPerDegree(lat);
  const sides = Math.max(3, feature.sides);
  return Array.from({ length: sides }, (_, i) => {
    const a = (i / sides) * Math.PI * 2;
    return [
      lng + (Math.cos(a) * feature.radius) / mLng,
      lat + (Math.sin(a) * feature.radius) / mLat,
      z,
    ] as [number, number, number];
  });
}
