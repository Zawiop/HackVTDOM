import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { computePlacementTransform, PlacementInputError } from '../src/services/placement.js';
import { LocalProjection, haversineMeters, normalizeDegrees } from '../src/geo/latlng.js';
import { area, bounds, minAreaRectangle, openRing } from '../src/geo/polygon.js';
import { buildingNamed, neighborsOf, allBuildings } from './helpers/fixtures.js';
import { extrudePolygonToObj, rectangularBlockObj, triangularPrismObj } from './helpers/meshFixtures.js';
import type { PlacementTransform } from '../src/types/placement.js';

/**
 * Ground-truth placement tests.
 *
 * Each case extrudes a *real* OSM building footprint into a mesh, applies a
 * known rotation / scale / offset, and asserts placement recovers it. A pass
 * means the maths is right, not merely that the output looked plausible.
 */

const objMesh = (obj: string) => ({ bytes: Buffer.from(obj, 'utf8'), path: 'fixture.obj' });

/** How far the placed origin ended up from the footprint's own centroid. */
function offsetFromCentroidMeters(transform: PlacementTransform, geometry: { lat: number; lng: number }[]) {
  const proj = new LocalProjection(geometry[0]!);
  const ring = openRing(proj.ringToMeters(geometry));
  let cx = 0;
  let cy = 0;
  for (const [x, y] of ring) {
    cx += x / ring.length;
    cy += y / ring.length;
  }
  const centroidLatLng = proj.toLatLng([cx, cy]);
  return haversineMeters(centroidLatLng, { lat: transform.position[0], lng: transform.position[1] });
}

describe('computePlacementTransform — ground truth on real OSM footprints', () => {
  it('recovers a near-perfect placement for a mesh built from the footprint itself', async () => {
    const building = buildingNamed('Davidson Hall');
    const { obj } = extrudePolygonToObj(building.geometry, { heightMeters: 18 });

    const transform = await computePlacementTransform({
      footprint: { polygon: building },
      mesh: objMesh(obj),
    });

    // The mesh IS the footprint, so placement should reach the ceiling that a
    // convex base outline can achieve against this (concave) polygon.
    expect(transform.diagnostics.fitQuality).toBeGreaterThan(0.99);
    expect(transform.diagnostics.iou).toBeCloseTo(transform.diagnostics.maxAchievableIou, 2);
    expect(transform.scale).toBeGreaterThan(0.95);
    expect(transform.scale).toBeLessThan(1.05);
    expect(transform.scaleMode).toBe('uniform');
    expect(transform.confidence).toBe('auto-high');
    expect(transform.flags).toEqual([]);
  });

  it.each([0, 37, 90, 145, 213, 300])(
    'recovers a mesh pre-rotated by %i degrees',
    async (preRotate) => {
      const building = buildingNamed('Derring Hall');
      const { obj } = extrudePolygonToObj(building.geometry, { preRotateDegrees: preRotate });

      const transform = await computePlacementTransform({
        footprint: { polygon: building },
        mesh: objMesh(obj),
      });

      // Rotating the mesh by -preRotate undoes the bake. Buildings are roughly
      // 2-fold symmetric in plan, so 180 degrees off is the same alignment.
      const expected = normalizeDegrees(-preRotate);
      const err = Math.min(
        normalizeDegrees(transform.rotationDegrees - expected),
        normalizeDegrees(expected - transform.rotationDegrees),
        normalizeDegrees(transform.rotationDegrees - expected + 180),
        normalizeDegrees(expected - transform.rotationDegrees + 180),
      );

      expect(err).toBeLessThan(2);
      expect(transform.diagnostics.fitQuality).toBeGreaterThan(0.95);
    },
  );

  it('keeps all four candidates, 90 degrees apart, for step 09 to reuse', async () => {
    const building = buildingNamed('Norris Hall');
    const { obj } = extrudePolygonToObj(building.geometry);

    const transform = await computePlacementTransform({
      footprint: { polygon: building },
      mesh: objMesh(obj),
    });

    expect(transform.scoredRotationCandidates).toHaveLength(4);
    expect([...transform.scoredRotationCandidates].map((c) => c.offsetDegrees).sort((a, b) => a - b))
      .toEqual([0, 90, 180, 270]);

    // Sorted best-first, every one scored, and none discarded.
    const ious = transform.scoredRotationCandidates.map((c) => c.iou);
    expect([...ious].sort((a, b) => b - a)).toEqual(ious);
    expect(transform.rotationDegrees).toBe(transform.scoredRotationCandidates[0]!.rotationDegrees);
    for (const candidate of transform.scoredRotationCandidates) {
      expect(candidate.iou).toBeGreaterThanOrEqual(0);
      expect(candidate.iou).toBeLessThanOrEqual(1);
      expect(candidate.scale).toBeGreaterThan(0);
    }

    // The four headings really are a quadrant sweep.
    const headings = transform.scoredRotationCandidates
      .map((c) => normalizeDegrees(c.rotationDegrees))
      .sort((a, b) => a - b);
    for (let i = 1; i < headings.length; i++) {
      expect(headings[i]! - headings[i - 1]!).toBeCloseTo(90, 4);
    }
  });

  it('lands the mesh on the footprint, not somewhere else on the planet', async () => {
    for (const name of ['Davidson Hall', 'Patton Hall', 'War Memorial Hall']) {
      const building = buildingNamed(name);
      const { obj } = extrudePolygonToObj(building.geometry, { preRotateDegrees: 63 });

      const transform = await computePlacementTransform({
        footprint: { polygon: building },
        mesh: objMesh(obj),
      });

      const [lat, lng] = transform.position;
      const offset = offsetFromCentroidMeters(transform, building.geometry);

      // Within the building, not merely within the county.
      expect(offset).toBeLessThan(2);
      expect(lat).toBeGreaterThan(37.2);
      expect(lat).toBeLessThan(37.3);
      expect(lng).toBeGreaterThan(-80.5);
      expect(lng).toBeLessThan(-80.4);
    }
  });
});

describe('scale (spec 08)', () => {
  it('prefers a single uniform factor when the proportions match', async () => {
    const building = buildingNamed('Hancock Hall');
    const { obj } = extrudePolygonToObj(building.geometry, { preScale: 0.5 });

    const transform = await computePlacementTransform({
      footprint: { polygon: building },
      mesh: objMesh(obj),
    });

    expect(transform.scaleMode).toBe('uniform');
    expect(transform.scale).toBeCloseTo(2, 1);
    expect(transform.scaleXYZ[0]).toBeCloseTo(transform.scaleXYZ[2], 6);
  });

  it('falls back to non-uniform only past the ~30%-undersized threshold', async () => {
    const building = buildingNamed('Davidson Hall');
    const proj = new LocalProjection(building.geometry[0]!);
    const rect = minAreaRectangle(openRing(proj.ringToMeters(building.geometry)));

    // Matches the building's long axis but is only a third as deep. Placement
    // aligns the axes itself, so the block needs no pre-rotation: uniform
    // scaling would leave it at ~33% coverage, far past the threshold.
    const skinny = rectangularBlockObj(rect.length, rect.width / 3, 15);

    const transform = await computePlacementTransform({
      footprint: { polygon: building },
      mesh: objMesh(skinny),
    });

    expect(transform.scaleMode).toBe('non-uniform');
    expect(transform.scaleXYZ[0]).not.toBeCloseTo(transform.scaleXYZ[2], 2);
    expect(transform.confidence).toBe('auto-low');
    expect(transform.flags.map((f) => f.code)).toContain('non-uniform-fallback');
  });

  it('does NOT stretch a mesh that is merely a little off proportion', async () => {
    const building = buildingNamed('Hahn Hall South');
    const proj = new LocalProjection(building.geometry[0]!);
    const rect = minAreaRectangle(openRing(proj.ringToMeters(building.geometry)));

    // 10% shallower — comfortably inside the 30% threshold.
    const block = rectangularBlockObj(rect.length, rect.width * 0.9, 15);

    const transform = await computePlacementTransform({
      footprint: { polygon: building },
      mesh: objMesh(block),
    });

    expect(transform.scaleMode).toBe('uniform');
    expect(transform.flags.map((f) => f.code)).not.toContain('non-uniform-fallback');
  });

  it('flags a units problem instead of absorbing it into the scale factor', async () => {
    const building = buildingNamed('Norris Hall');
    // Authored in centimetres rather than metres — step 07's job to catch.
    const { obj } = extrudePolygonToObj(building.geometry, { preScale: 0.01 });

    const transform = await computePlacementTransform({
      footprint: { polygon: building },
      mesh: objMesh(obj),
    });

    expect(transform.scale).toBeCloseTo(100, 0);
    expect(transform.confidence).toBe('auto-low');
    const flag = transform.flags.find((f) => f.code === 'implausible-scale');
    expect(flag?.subStep).toBe('mesh');
    expect(flag?.message).toMatch(/units problem/i);
  });
});

describe('ground alignment (spec 08)', () => {
  it('leaves z at 0 when step 07 base-centred the pivot', async () => {
    const building = buildingNamed('Patton Hall');
    const { obj } = extrudePolygonToObj(building.geometry, { heightMeters: 20 });

    const transform = await computePlacementTransform({
      footprint: { polygon: building },
      mesh: objMesh(obj),
    });

    expect(transform.position[2]).toBeCloseTo(0, 6);
    expect(transform.ground.meshBaseOffsetUnits).toBeCloseTo(0, 6);
  });

  it('sinks a floating mesh back to the ground, and says so', async () => {
    const building = buildingNamed('Patton Hall');
    const { obj } = extrudePolygonToObj(building.geometry, {
      heightMeters: 20,
      baseOffsetUnits: 7, // 7 m above its own origin
    });

    const transform = await computePlacementTransform({
      footprint: { polygon: building },
      mesh: objMesh(obj),
    });

    expect(transform.ground.meshBaseOffsetUnits).toBeCloseTo(7, 4);
    // z pulls the model down by exactly the scaled base offset.
    expect(transform.position[2]).toBeCloseTo(-7 * transform.scaleXYZ[1], 3);
    expect(transform.flags.map((f) => f.code)).toContain('pivot-not-base-centred');
  });

  it('lifts a sunken mesh up to the ground', async () => {
    const building = buildingNamed('Patton Hall');
    const { obj } = extrudePolygonToObj(building.geometry, { baseOffsetUnits: -4 });

    const transform = await computePlacementTransform({
      footprint: { polygon: building },
      mesh: objMesh(obj),
    });

    expect(transform.position[2]).toBeGreaterThan(0);
    expect(transform.position[2]).toBeCloseTo(4 * transform.scaleXYZ[1], 3);
  });

  it('keeps the scaled height physically plausible for a building', async () => {
    const building = buildingNamed('Derring Hall');
    const { obj } = extrudePolygonToObj(building.geometry, { heightMeters: 24 });

    const transform = await computePlacementTransform({
      footprint: { polygon: building },
      mesh: objMesh(obj),
    });

    expect(transform.diagnostics.scaledHeightMeters).toBeGreaterThan(15);
    expect(transform.diagnostics.scaledHeightMeters).toBeLessThan(40);
  });
});

describe('collision against real neighbouring footprints (spec 08)', () => {
  it('reuses the neighbours from step 02 and reports a clean placement', async () => {
    const building = buildingNamed('War Memorial Hall');
    const neighbors = neighborsOf(building);
    const { obj } = extrudePolygonToObj(building.geometry);

    const transform = await computePlacementTransform({
      footprint: { polygon: building, neighbors },
      mesh: objMesh(obj),
    });

    expect(transform.collision.neighborsChecked).toBe(neighbors.length);
    expect(transform.collision.neighborsChecked).toBeGreaterThan(10);
    expect(transform.collision.worstOverlapRatio).toBeLessThan(0.15);
    expect(transform.flags.map((f) => f.code)).not.toContain('neighbor-overlap');
  });

  it('never counts the target building as its own neighbour', async () => {
    const building = buildingNamed('Davidson Hall');
    const { obj } = extrudePolygonToObj(building.geometry);

    // Pass the whole set, target included, the way a naive step 02 result would.
    const transform = await computePlacementTransform({
      footprint: { polygon: building, neighbors: allBuildings() },
      mesh: objMesh(obj),
    });

    expect(transform.collision.neighborsChecked).toBe(allBuildings().length - 1);
    expect(transform.collision.overlaps.map((o) => String(o.neighborId))).not.toContain(
      String(building.id),
    );
  });

  it('flags an overlap when the mesh is scaled out over its neighbours', async () => {
    const building = buildingNamed('Davidson Hall');
    const neighbors = neighborsOf(building);

    // A footprint stretched far past the real one, so the placed mesh spills
    // across the buildings next door.
    const proj = new LocalProjection(building.geometry[0]!);
    const ring = openRing(proj.ringToMeters(building.geometry));
    let cx = 0;
    let cy = 0;
    for (const [x, y] of ring) {
      cx += x / ring.length;
      cy += y / ring.length;
    }
    const inflated = ring.map(([x, y]) => proj.toLatLng([cx + (x - cx) * 4, cy + (y - cy) * 4]));

    const { obj } = extrudePolygonToObj(inflated);

    const transform = await computePlacementTransform({
      footprint: { polygon: { ...building, geometry: inflated }, neighbors },
      mesh: objMesh(obj),
    });

    expect(transform.collision.overlaps.length).toBeGreaterThan(0);
    expect(transform.collision.worstOverlapRatio).toBeGreaterThan(0.15);
    expect(transform.confidence).toBe('auto-low');
    expect(transform.flags.map((f) => f.code)).toContain('neighbor-overlap');
  });
});

describe('confidence (spec 08)', () => {
  it("propagates step 02's low footprint confidence as a distinct flag", async () => {
    const building = buildingNamed('Norris Hall');
    const { obj } = extrudePolygonToObj(building.geometry);

    const transform = await computePlacementTransform({
      footprint: { polygon: building, confidence: 'low' },
      mesh: objMesh(obj),
    });

    expect(transform.confidence).toBe('auto-low');
    const flag = transform.flags.find((f) => f.subStep === 'footprint');
    expect(flag?.code).toBe('footprint-match-low');
  });

  it('never lets a later clean sub-check clear an earlier flag', async () => {
    const building = buildingNamed('Norris Hall');
    const neighbors = neighborsOf(building);
    // Footprint flagged low, but rotation, scale, collision and ground are all fine.
    const { obj } = extrudePolygonToObj(building.geometry);

    const transform = await computePlacementTransform({
      footprint: { polygon: building, neighbors, confidence: 'low' },
      mesh: objMesh(obj),
    });

    expect(transform.diagnostics.fitQuality).toBeGreaterThan(0.95);
    expect(transform.collision.worstOverlapRatio).toBeLessThan(0.15);
    expect(transform.position[2]).toBeCloseTo(0, 6);
    // Everything after the footprint check passed, and it is still auto-low.
    expect(transform.confidence).toBe('auto-low');
    expect(transform.flags).toHaveLength(1);
  });

  it('flags a mesh whose outline is the wrong shape for the footprint', async () => {
    const building = buildingNamed('Sandy Hall'); // near-rectangular in plan
    const proj = new LocalProjection(building.geometry[0]!);
    const rect = minAreaRectangle(openRing(proj.ringToMeters(building.geometry)));

    // A triangle fills about half of the rectangle it is inscribed in, however
    // it is rotated or scaled, so fit quality cannot reach the threshold.
    const transform = await computePlacementTransform({
      footprint: { polygon: building },
      mesh: objMesh(triangularPrismObj(rect.length, rect.width, 12)),
    });

    expect(transform.diagnostics.fitQuality).toBeLessThan(0.6);
    expect(transform.confidence).toBe('auto-low');
    expect(transform.flags.map((f) => f.code)).toContain('low-iou');
  });

  it('flags a long thin bar as the wrong building, by some check or other', async () => {
    const building = buildingNamed('Sandy Hall');
    const transform = await computePlacementTransform({
      footprint: { polygon: building },
      mesh: objMesh(rectangularBlockObj(120, 3, 10)),
    });

    // Which check catches it matters less than that nothing waves it through.
    expect(transform.confidence).toBe('auto-low');
    expect(transform.flags.length).toBeGreaterThan(0);
  });

  it("reports step 02's derived values disagreeing rather than working around them", async () => {
    const building = buildingNamed('Patton Hall');
    const { obj } = extrudePolygonToObj(building.geometry);

    const transform = await computePlacementTransform({
      footprint: {
        polygon: building,
        footprintWidthMeters: 999, // nonsense from upstream
        longestEdgeBearingDegrees: 7,
      },
      mesh: objMesh(obj),
    });

    expect(transform.confidence).toBe('auto-low');
    const flag = transform.flags.find((f) => f.code === 'derived-values-disagree');
    expect(flag).toBeDefined();
    expect(flag!.message).toMatch(/footprintWidthMeters reported 999/);
    expect(transform.diagnostics.footprintDerivedMismatch?.length).toBeGreaterThan(0);
  });
});

describe('real binary GLB input', () => {
  it('places a real .glb against a real footprint end to end', async () => {
    const building = buildingNamed('Sandy Hall');

    const transform = await computePlacementTransform({
      footprint: { polygon: building, neighbors: neighborsOf(building) },
      mesh: { bytes: readFileSync('test/fixtures/Duck.glb'), path: 'Duck.glb' },
    });

    // The duck is not a building, so the fit is poor — but the record must
    // still be complete, finite and on the footprint.
    expect(Number.isFinite(transform.rotationDegrees)).toBe(true);
    expect(transform.scale).toBeGreaterThan(0);
    expect(transform.scoredRotationCandidates).toHaveLength(4);
    // A duck is not a building, so the fit is poor and the IoU refinement drags
    // it a few metres. It must still land on the footprint, not off in space.
    const proj = new LocalProjection(building.geometry[0]!);
    const fpBounds = bounds(openRing(proj.ringToMeters(building.geometry)));
    const [placedE, placedN] = proj.toMeters({ lat: transform.position[0], lng: transform.position[1] });

    expect(placedE).toBeGreaterThanOrEqual(fpBounds.minX);
    expect(placedE).toBeLessThanOrEqual(fpBounds.maxX);
    expect(placedN).toBeGreaterThanOrEqual(fpBounds.minY);
    expect(placedN).toBeLessThanOrEqual(fpBounds.maxY);
    expect(transform.diagnostics.upAxis).toBe('y');
  });
});

describe('input validation', () => {
  it('rejects a polygon with too few vertices', async () => {
    await expect(
      computePlacementTransform({
        footprint: { polygon: { geometry: [{ lat: 37.2, lng: -80.4 }, { lat: 37.2, lng: -80.3 }] } },
        mesh: objMesh(rectangularBlockObj(10, 10, 10)),
      }),
    ).rejects.toThrow(PlacementInputError);
  });

  it('rejects a footprint too small to place against', async () => {
    const tiny = [
      { lat: 37.2284, lng: -80.4234 },
      { lat: 37.2284, lng: -80.42339 },
      { lat: 37.22841, lng: -80.42339 },
    ];
    await expect(
      computePlacementTransform({
        footprint: { polygon: { geometry: tiny } },
        mesh: objMesh(rectangularBlockObj(10, 10, 10)),
      }),
    ).rejects.toThrow(/too small/i);
  });

  it('rejects a mesh input with nothing to load', async () => {
    const building = buildingNamed('Norris Hall');
    await expect(
      computePlacementTransform({ footprint: { polygon: building }, mesh: {} }),
    ).rejects.toThrow(PlacementInputError);
  });
});

describe('the 180-degree flip is reported, not flagged', () => {
  it('records the flip margin without routing the placement to manual review', async () => {
    const building = buildingNamed('Derring Hall');
    const { obj } = extrudePolygonToObj(building.geometry);

    const transform = await computePlacementTransform({
      footprint: { polygon: building },
      mesh: objMesh(obj),
    });

    // The flip scores almost as well — a footprint cannot tell a facade from
    // its back — and that is information for step 09, not a confidence problem.
    expect(transform.diagnostics.rotationFlipMargin).not.toBeNull();
    expect(Math.abs(transform.diagnostics.rotationFlipMargin!)).toBeLessThan(0.1);
    expect(transform.flags.map((f) => f.code)).not.toContain('rotation-ambiguous');
    expect(transform.confidence).toBe('auto-high');

    // The flip is still in the candidate list for the UI to offer.
    const winner = transform.scoredRotationCandidates[0]!;
    const flip = transform.scoredRotationCandidates.find(
      (c) => Math.abs(c.offsetDegrees - winner.offsetDegrees) === 180,
    );
    expect(flip).toBeDefined();
  });

  it('still flags a genuine across-vs-along ambiguity', async () => {
    const building = buildingNamed('Sandy Hall');
    const proj = new LocalProjection(building.geometry[0]!);
    const rect = minAreaRectangle(openRing(proj.ringToMeters(building.geometry)));

    // A square mesh fits equally well at every quadrant, which is the real
    // ambiguity — 90 degrees out, not 180.
    const square = rectangularBlockObj(rect.length, rect.length, 12);
    const transform = await computePlacementTransform({
      footprint: { polygon: building },
      mesh: objMesh(square),
    });

    expect(transform.flags.map((f) => f.code)).toContain('rotation-ambiguous');
    expect(transform.confidence).toBe('auto-low');
  });
});

describe('collision confirms box hits against the real polygons', () => {
  it('does not flag diagonal neighbours whose boxes overlap but buildings do not', async () => {
    // Every real VT footprint, placed on itself, with all its real neighbours.
    // Campus is laid out at ~45 degrees, so axis-aligned boxes overlap
    // constantly; none of these are actual collisions.
    let flagged = 0;
    let checked = 0;

    for (const building of allBuildings()) {
      const { obj } = extrudePolygonToObj(building.geometry, { heightMeters: 20 });
      const transform = await computePlacementTransform({
        footprint: { polygon: building, neighbors: neighborsOf(building) },
        mesh: objMesh(obj),
      });
      checked++;
      if (transform.flags.some((f) => f.code === 'neighbor-overlap')) flagged++;
    }

    expect(checked).toBeGreaterThan(25);
    expect(flagged).toBe(0);
  });

  it('every real building places at auto-high against its own footprint', async () => {
    // The strongest end-to-end assertion available without teammate data: a
    // mesh that genuinely is the building must never be routed to correction.
    for (const building of allBuildings()) {
      const { obj } = extrudePolygonToObj(building.geometry, { heightMeters: 20 });
      const transform = await computePlacementTransform({
        footprint: { polygon: building, neighbors: neighborsOf(building) },
        mesh: objMesh(obj),
      });

      expect(transform.confidence, `${building.tags?.name ?? building.id}: ${JSON.stringify(transform.flags)}`)
        .toBe('auto-high');
      expect(transform.diagnostics.fitQuality).toBeGreaterThan(0.95);
      expect(transform.scale).toBeCloseTo(1, 1);
      expect(transform.position[2]).toBeCloseTo(0, 6);
    }
  });
});
