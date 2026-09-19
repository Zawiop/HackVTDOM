import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import {
  LocalProjection,
  bearingDegrees,
  haversineMeters,
  metersPerDegreeLat,
  metersPerDegreeLng,
} from '../src/geo/latlng.js';
import {
  area,
  bboxOverlapArea,
  bounds,
  centroid,
  convexHull,
  intersectionArea,
  iou,
  longestEdgeBearing,
  rotateRing,
  scaleRing,
  translateRing,
  type Ring,
} from '../src/geo/polygon.js';
import { meshBaseFootprint, parseGlb, parseObj, parseMesh, MeshParseError } from '../src/geo/mesh.js';
import { buildingNamed } from './helpers/fixtures.js';
import { rectangularBlockObj } from './helpers/meshFixtures.js';

const unitSquare: Ring = [
  [0, 0],
  [10, 0],
  [10, 10],
  [0, 10],
];

describe('local projection', () => {
  it('round-trips a real lat/lng through metres without drift', () => {
    const anchor = { lat: 37.2284, lng: -80.4234 };
    const proj = new LocalProjection(anchor);
    const point = { lat: 37.22885, lng: -80.42295 };

    const back = proj.toLatLng(proj.toMeters(point));
    expect(back.lat).toBeCloseTo(point.lat, 9);
    expect(back.lng).toBeCloseTo(point.lng, 9);
  });

  it('agrees with haversine over building-scale distances', () => {
    const anchor = { lat: 37.2284, lng: -80.4234 };
    const proj = new LocalProjection(anchor);
    const other = { lat: 37.2294, lng: -80.4224 };

    const [e, n] = proj.toMeters(other);
    const planar = Math.hypot(e, n);
    const geodesic = haversineMeters(anchor, other);

    // ~3.7 cm apart over 142 m (0.026%). Well inside what building placement
    // needs, and the error shrinks quadratically as the anchor gets closer.
    expect(Math.abs(planar - geodesic)).toBeLessThan(0.05);
  });

  it('metres-per-degree varies with latitude, as spec 02 requires', () => {
    expect(metersPerDegreeLng(0)).toBeGreaterThan(111_000);
    expect(metersPerDegreeLng(60)).toBeLessThan(56_500);
    expect(metersPerDegreeLat(0)).toBeLessThan(metersPerDegreeLat(89));
  });

  it('bearing is a compass heading: north 0, east 90', () => {
    const from = { lat: 37.2284, lng: -80.4234 };
    expect(bearingDegrees(from, { lat: 37.2294, lng: -80.4234 })).toBeCloseTo(0, 1);
    expect(bearingDegrees(from, { lat: 37.2284, lng: -80.4224 })).toBeCloseTo(90, 1);
    expect(bearingDegrees(from, { lat: 37.2274, lng: -80.4234 })).toBeCloseTo(180, 1);
  });
});

describe('polygon primitives', () => {
  it('computes area and centroid', () => {
    expect(area(unitSquare)).toBeCloseTo(100, 9);
    expect(centroid(unitSquare)).toEqual([5, 5]);
  });

  it('handles a closed ring the same as an open one (OSM sends closed)', () => {
    const closed: Ring = [...unitSquare, [0, 0]];
    expect(area(closed)).toBeCloseTo(area(unitSquare), 9);
    expect(centroid(closed)).toEqual(centroid(unitSquare));
  });

  it('rotates clockwise in compass convention, preserving area', () => {
    const rotated = rotateRing(unitSquare, 90, [5, 5]);
    expect(area(rotated)).toBeCloseTo(100, 9);
    // Heading 90 turns north-facing geometry to face east.
    const [x, y] = rotated[0]!;
    expect(x).toBeCloseTo(0, 9);
    expect(y).toBeCloseTo(10, 9);
  });

  it('a 360 degree rotation is the identity', () => {
    const there = rotateRing(unitSquare, 360);
    there.forEach(([x, y], i) => {
      expect(x).toBeCloseTo(unitSquare[i]![0], 9);
      expect(y).toBeCloseTo(unitSquare[i]![1], 9);
    });
  });

  it('scales area quadratically', () => {
    expect(area(scaleRing(unitSquare, 2))).toBeCloseTo(400, 9);
    expect(area(scaleRing(unitSquare, [2, 3]))).toBeCloseTo(600, 9);
  });

  it('IoU is 1 for identical rings and 0 for disjoint ones', () => {
    expect(iou(unitSquare, unitSquare)).toBeCloseTo(1, 9);
    expect(iou(unitSquare, translateRing(unitSquare, [100, 100]))).toBe(0);
  });

  it('IoU matches the analytic value for a known half-overlap', () => {
    const shifted = translateRing(unitSquare, [5, 0]);
    // Intersection 50, union 150.
    expect(intersectionArea(unitSquare, shifted)).toBeCloseTo(50, 6);
    expect(iou(unitSquare, shifted)).toBeCloseTo(50 / 150, 6);
  });

  it('IoU is symmetric and bounded', () => {
    const other = translateRing(scaleRing(unitSquare, 1.4), [2, 3]);
    const forward = iou(unitSquare, other);
    expect(forward).toBeCloseTo(iou(other, unitSquare), 9);
    expect(forward).toBeGreaterThan(0);
    expect(forward).toBeLessThan(1);
  });

  it('handles a concave ring — real OSM footprints are L-shaped', () => {
    const lShape: Ring = [
      [0, 0],
      [10, 0],
      [10, 4],
      [4, 4],
      [4, 10],
      [0, 10],
    ];
    expect(area(lShape)).toBeCloseTo(64, 6);
    expect(iou(lShape, lShape)).toBeCloseTo(1, 6);
    // Its convex hull is strictly larger, so IoU against the hull is < 1.
    expect(iou(lShape, convexHull(lShape))).toBeLessThan(1);
  });

  it('longest-edge bearing folds to [0,180) — a wall has no direction', () => {
    const wide: Ring = [
      [0, 0],
      [30, 0],
      [30, 5],
      [0, 5],
    ];
    expect(longestEdgeBearing(wide)).toBeCloseTo(90, 6);

    const tall: Ring = [
      [0, 0],
      [5, 0],
      [5, 30],
      [0, 30],
    ];
    expect(longestEdgeBearing(tall)).toBeCloseTo(0, 6);
  });

  it('bbox overlap is zero for adjacent-but-not-touching boxes', () => {
    expect(bboxOverlapArea(unitSquare, translateRing(unitSquare, [10.5, 0]))).toBe(0);
    expect(bboxOverlapArea(unitSquare, translateRing(unitSquare, [5, 0]))).toBeCloseTo(50, 6);
  });

  it('convex hull of a point cloud wraps every point', () => {
    const hull = convexHull([
      [0, 0],
      [5, 1],
      [10, 0],
      [10, 10],
      [0, 10],
      [5, 5],
    ]);
    expect(area(hull)).toBeCloseTo(100, 6);
    expect(hull.length).toBe(4); // the two interior points are dropped
  });
});

describe('real OSM footprints', () => {
  it('projects Davidson Hall to a plausible building-sized polygon', () => {
    const building = buildingNamed('Davidson Hall');
    const proj = new LocalProjection(building.geometry[0]!);
    const ring = proj.ringToMeters(building.geometry);

    const a = area(ring);
    const b = bounds(ring);

    expect(a).toBeGreaterThan(200);
    expect(a).toBeLessThan(20_000);
    expect(b.width).toBeGreaterThan(10);
    expect(b.depth).toBeGreaterThan(10);
  });

  it('VT buildings sit diagonal to the compass grid', () => {
    // Measured from the captured fixtures: bearings cluster near 45 and 136
    // degrees, so an axis-aligned bounding box overstates these footprints
    // badly (Davidson Hall fills only 36% of its own AABB). This is the reason
    // the scale fit in placement.ts works in the mesh's frame rather than
    // against east/north extents.
    const diagonal = ['Davidson Hall', 'Derring Hall', 'Norris Hall', 'Williams Hall'].map(
      (name) => {
        const building = buildingNamed(name);
        const proj = new LocalProjection(building.geometry[0]!);
        const ring = proj.ringToMeters(building.geometry);
        const bearing = longestEdgeBearing(ring);
        const bb = bounds(ring);
        return { bearing, aabbFill: area(ring) / (bb.width * bb.depth) };
      },
    );

    for (const { bearing, aabbFill } of diagonal) {
      const offGrid = Math.min(bearing % 90, 90 - (bearing % 90));
      expect(offGrid).toBeGreaterThan(20);
      expect(aabbFill).toBeLessThan(0.6);
    }
  });

  it('every captured building has a sane bearing', () => {
    for (const name of ['Davidson Hall', 'Norris Hall', 'Patton Hall']) {
      const building = buildingNamed(name);
      const proj = new LocalProjection(building.geometry[0]!);
      const bearing = longestEdgeBearing(proj.ringToMeters(building.geometry));
      expect(bearing).toBeGreaterThanOrEqual(0);
      expect(bearing).toBeLessThan(180);
    }
  });
});

describe('mesh parsing', () => {
  it('reads a real GLB and applies its node transforms', () => {
    const geometry = parseGlb(readFileSync('test/fixtures/Box.glb'));
    expect(geometry.vertexCount).toBe(24);
    expect(geometry.min).toEqual([-0.5, -0.5, -0.5]);
    expect(geometry.max).toEqual([0.5, 0.5, 0.5]);
  });

  it('reads a denser real GLB with a transformed node', () => {
    const geometry = parseGlb(readFileSync('test/fixtures/Duck.glb'));
    expect(geometry.vertexCount).toBeGreaterThan(2000);
    // Duck.glb's root node carries a 0.01 scale; a parser that ignored node
    // transforms would report extents around 100x larger than this.
    expect(geometry.max[1]! - geometry.min[1]!).toBeLessThan(5);
  });

  it('detects the format from content, not just the extension', () => {
    expect(parseMesh(readFileSync('test/fixtures/Box.glb')).vertexCount).toBe(24);
    expect(parseMesh(Buffer.from(rectangularBlockObj(10, 6, 12)), 'x.obj').vertexCount).toBe(8);
  });

  it('rejects junk rather than returning an empty mesh', () => {
    expect(() => parseMesh(Buffer.from('this is not a mesh'))).toThrow(MeshParseError);
    expect(() => parseGlb(Buffer.from('nope'))).toThrow(MeshParseError);
  });

  it('extracts a cube base outline from its four base corners, not all 24 verts', () => {
    const footprint = meshBaseFootprint(parseGlb(readFileSync('test/fixtures/Box.glb')));
    expect(footprint.outline).toHaveLength(4);
    expect(area(footprint.outline)).toBeCloseTo(1, 6);
    expect(footprint.width).toBeCloseTo(1, 6);
    expect(footprint.heightUnits).toBeCloseTo(1, 6);
  });

  it('honours the up-axis convention', () => {
    // A block 20m wide, 6m deep, 30m tall, authored Y-up.
    const geometry = parseObj(rectangularBlockObj(20, 6, 30, { upAxis: 'y' }));

    const yUp = meshBaseFootprint(geometry, { upAxis: 'y' });
    expect(yUp.width).toBeCloseTo(20, 6);
    expect(yUp.depth).toBeCloseTo(6, 6);
    expect(yUp.heightUnits).toBeCloseTo(30, 6);

    // Read as Z-up, the same file yields a wrong-looking 20x30 footprint —
    // which is exactly the symptom step 08 flags rather than silently fixing.
    const zUp = meshBaseFootprint(geometry, { upAxis: 'z' });
    expect(zUp.heightUnits).toBeCloseTo(6, 6);
  });

  it('reports the base offset so ground alignment can correct for it', () => {
    const floating = parseObj(
      rectangularBlockObj(10, 10, 10)
        .split('\n')
        .map((l) => (l.startsWith('v ') ? `v ${l.split(' ')[1]} ${Number(l.split(' ')[2]) + 5} ${l.split(' ')[3]}` : l))
        .join('\n'),
    );
    expect(meshBaseFootprint(floating).baseOffset).toBeCloseTo(5, 6);
  });
});
