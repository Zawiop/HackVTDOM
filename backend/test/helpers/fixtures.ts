import { readFileSync } from 'node:fs';
import path from 'node:path';
import type { LatLng } from '../../src/geo/latlng.js';
import type { FootprintPolygon } from '../../src/types/placement.js';

/**
 * Real OpenStreetMap building footprints around Virginia Tech, captured from
 * the Overpass API (the same query step 02 issues) and checked in so tests
 * don't depend on a shared public server being up.
 *
 * Source: overpass-api.de, `way["building"](around:250,<lat>,<lng>);out geom;`
 * © OpenStreetMap contributors, ODbL.
 */

interface OverpassWay {
  type: string;
  id: number;
  geometry: Array<{ lat: number; lon: number }>;
  tags?: Record<string, string>;
}

interface FixtureFile {
  [site: string]: { query: { lat: number; lng: number; radius: number }; elements: OverpassWay[] };
}

const raw = JSON.parse(
  readFileSync(path.resolve(process.cwd(), 'test/fixtures/osm-footprints.json'), 'utf8'),
) as FixtureFile;

export function toFootprintPolygon(way: OverpassWay): FootprintPolygon {
  return {
    id: way.id,
    geometry: way.geometry.map((p): LatLng => ({ lat: p.lat, lng: p.lon })),
    ...(way.tags ? { tags: way.tags } : {}),
  };
}

/** Every captured building, across all sites, de-duplicated by OSM way id. */
export function allBuildings(): FootprintPolygon[] {
  const byId = new Map<number, FootprintPolygon>();
  for (const site of Object.values(raw)) {
    for (const way of site.elements) byId.set(way.id, toFootprintPolygon(way));
  }
  return [...byId.values()];
}

/** Look a building up by its OSM `name` tag. */
export function buildingNamed(name: string): FootprintPolygon {
  const match = allBuildings().find((b) => b.tags?.name === name);
  if (!match) {
    const names = allBuildings()
      .map((b) => b.tags?.name)
      .filter(Boolean);
    throw new Error(`No fixture building named "${name}". Have: ${names.join(', ')}`);
  }
  return match;
}

/** Everything except the named building — step 02's neighbour list. */
export function neighborsOf(target: FootprintPolygon): FootprintPolygon[] {
  return allBuildings().filter((b) => b.id !== target.id);
}
