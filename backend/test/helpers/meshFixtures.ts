import { LocalProjection, type LatLng } from '../../src/geo/latlng.js';
import { openRing, rotateRing, type Ring } from '../../src/geo/polygon.js';

/**
 * Builds mesh files with a *known correct answer*.
 *
 * Every fixture here starts from a real OSM building polygon, extrudes it into
 * a solid, and then applies a deliberate rotation / scale / vertical offset. The
 * placement transform is correct exactly when it recovers what was applied — so
 * these are ground-truth tests of the maths, not assertions about a mesh that
 * happens to look plausible.
 */

export interface ExtrudeOptions {
  heightMeters?: number;
  /** Compass heading baked into the mesh. Placement should recover its inverse. */
  preRotateDegrees?: number;
  /** Uniform scale baked in, e.g. 0.01 to simulate a units mistake. */
  preScale?: number;
  /** Lift the whole mesh off its own origin, simulating a bad step 07 pivot. */
  baseOffsetUnits?: number;
  upAxis?: 'y' | 'z';
}

export interface ExtrudedMesh {
  obj: string;
  /** The ring the mesh was built from, in metres relative to the anchor. */
  sourceRing: Ring;
  anchor: LatLng;
}

/**
 * Extrude a lat/lng ring into a Wavefront OBJ solid.
 *
 * The polygon is projected into the same local metre frame placement uses, then
 * re-centred on its own centroid so the model origin sits at the base centre —
 * which is exactly what step 07 is specified to produce.
 */
export function extrudePolygonToObj(
  geometry: LatLng[],
  options: ExtrudeOptions = {},
): ExtrudedMesh {
  const height = options.heightMeters ?? 12;
  const scale = options.preScale ?? 1;
  const baseOffset = options.baseOffsetUnits ?? 0;
  const upAxis = options.upAxis ?? 'y';

  const anchor = geometry[0]!;
  const projection = new LocalProjection(anchor);
  const ring = openRing(projection.ringToMeters(geometry));

  // Base-centre the pivot the way step 07 is meant to.
  const cx = ring.reduce((s, p) => s + p[0], 0) / ring.length;
  const cy = ring.reduce((s, p) => s + p[1], 0) / ring.length;
  const centred: Ring = ring.map(([x, y]) => [x - cx, y - cy]);

  const oriented = options.preRotateDegrees
    ? rotateRing(centred, options.preRotateDegrees)
    : centred;

  const lines: string[] = [
    '# Ground-truth fixture: a real OSM footprint extruded to a solid.',
    `# height=${height}m preRotate=${options.preRotateDegrees ?? 0} preScale=${scale} up=${upAxis}`,
  ];

  const vertex = (horizA: number, horizB: number, up: number) => {
    const a = horizA * scale;
    const b = horizB * scale;
    const u = up * scale + baseOffset;
    // glTF's Y-up convention puts the ground plane on X/Z.
    return upAxis === 'y' ? `v ${a} ${u} ${b}` : `v ${a} ${b} ${u}`;
  };

  for (const [x, y] of oriented) lines.push(vertex(x, y, 0));
  for (const [x, y] of oriented) lines.push(vertex(x, y, height));

  // Side quads plus a cap, so the solid is a real closed-ish mesh rather than
  // a bare point cloud.
  const n = oriented.length;
  for (let i = 0; i < n; i++) {
    const a = i + 1;
    const b = ((i + 1) % n) + 1;
    lines.push(`f ${a} ${b} ${b + n} ${a + n}`);
  }
  lines.push(`f ${Array.from({ length: n }, (_, i) => i + 1 + n).join(' ')}`);

  return { obj: lines.join('\n') + '\n', sourceRing: centred, anchor };
}

/** A plain rectangular block, for tests that want a shape with no OSM quirks. */
export function rectangularBlockObj(
  widthMeters: number,
  depthMeters: number,
  heightMeters: number,
  options: { preRotateDegrees?: number; upAxis?: 'y' | 'z' } = {},
): string {
  const upAxis = options.upAxis ?? 'y';
  const hw = widthMeters / 2;
  const hd = depthMeters / 2;

  let base: Ring = [
    [-hw, -hd],
    [hw, -hd],
    [hw, hd],
    [-hw, hd],
  ];
  if (options.preRotateDegrees) base = rotateRing(base, options.preRotateDegrees);

  const lines = ['# Rectangular block fixture'];
  for (const [x, y] of base) lines.push(upAxis === 'y' ? `v ${x} 0 ${y}` : `v ${x} ${y} 0`);
  for (const [x, y] of base) {
    lines.push(upAxis === 'y' ? `v ${x} ${heightMeters} ${y}` : `v ${x} ${y} ${heightMeters}`);
  }
  return lines.join('\n') + '\n';
}

/**
 * A triangular prism. Its base outline is convex but a poor match for any
 * rectangular footprint, so it exercises the low-fit-quality path without
 * tripping the scale or collision checks first.
 */
export function triangularPrismObj(
  baseMeters: number,
  depthMeters: number,
  heightMeters: number,
): string {
  const base: Ring = [
    [-baseMeters / 2, -depthMeters / 2],
    [baseMeters / 2, -depthMeters / 2],
    [0, depthMeters / 2],
  ];
  const lines = ['# Triangular prism fixture'];
  for (const [x, y] of base) lines.push(`v ${x} 0 ${y}`);
  for (const [x, y] of base) lines.push(`v ${x} ${heightMeters} ${y}`);
  return lines.join('\n') + '\n';
}
