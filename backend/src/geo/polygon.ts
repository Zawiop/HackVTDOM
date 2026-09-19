// polygon-clipping ships CommonJS. A namespace import (`import * as`) puts the
// functions on `.default` under Node's ESM interop while some bundlers hand
// back a callable namespace — a difference that silently turned every IoU into
// zero under `node`/`tsx` while the bundled test run looked fine. Take the
// default export explicitly so both resolve to the same object.
import polygonClipping from 'polygon-clipping';
import { normalizeDegrees, type PointMeters } from './latlng.js';

/**
 * 2D polygon maths in the local metre frame (see latlng.ts).
 *
 * Convention throughout: a point is [east, north], and an angle is a **compass
 * heading** — 0 = north, 90 = east, increasing clockwise. That matches the
 * `rotationDegrees` the rest of the pipeline speaks, and it is the opposite
 * winding to the usual maths convention, so rotation is written out explicitly
 * below rather than borrowed from a standard rotation matrix.
 */

export type Ring = PointMeters[];

export interface BoundsMeters {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
  width: number;
  depth: number;
}

const DEG = Math.PI / 180;

/** Drop a duplicated closing vertex; OSM ways arrive closed, the maths wants open. */
export function openRing(ring: Ring): Ring {
  if (ring.length < 2) return [...ring];
  const first = ring[0]!;
  const last = ring[ring.length - 1]!;
  const closed = Math.abs(first[0] - last[0]) < 1e-9 && Math.abs(first[1] - last[1]) < 1e-9;
  return closed ? ring.slice(0, -1) : [...ring];
}

/** Re-add the closing vertex; polygon-clipping wants closed rings. */
export function closeRing(ring: Ring): Ring {
  const open = openRing(ring);
  return open.length > 0 ? [...open, open[0]!] : open;
}

/** Signed shoelace area. Positive = counter-clockwise in [east, north] space. */
export function signedArea(ring: Ring): number {
  const r = openRing(ring);
  let sum = 0;
  for (let i = 0; i < r.length; i++) {
    const a = r[i]!;
    const b = r[(i + 1) % r.length]!;
    sum += a[0] * b[1] - b[0] * a[1];
  }
  return sum / 2;
}

export function area(ring: Ring): number {
  return Math.abs(signedArea(ring));
}

/** Area-weighted centroid. Falls back to the vertex mean for degenerate rings. */
export function centroid(ring: Ring): PointMeters {
  const r = openRing(ring);
  if (r.length === 0) return [0, 0];
  if (r.length < 3) {
    const n = r.length;
    return [r.reduce((s, p) => s + p[0], 0) / n, r.reduce((s, p) => s + p[1], 0) / n];
  }

  let cx = 0;
  let cy = 0;
  let a2 = 0;
  for (let i = 0; i < r.length; i++) {
    const p = r[i]!;
    const q = r[(i + 1) % r.length]!;
    const cross = p[0] * q[1] - q[0] * p[1];
    a2 += cross;
    cx += (p[0] + q[0]) * cross;
    cy += (p[1] + q[1]) * cross;
  }

  if (Math.abs(a2) < 1e-12) {
    const n = r.length;
    return [r.reduce((s, p) => s + p[0], 0) / n, r.reduce((s, p) => s + p[1], 0) / n];
  }
  return [cx / (3 * a2), cy / (3 * a2)];
}

export function bounds(ring: Ring): BoundsMeters {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const [x, y] of ring) {
    if (x < minX) minX = x;
    if (x > maxX) maxX = x;
    if (y < minY) minY = y;
    if (y > maxY) maxY = y;
  }
  return { minX, minY, maxX, maxY, width: maxX - minX, depth: maxY - minY };
}

/**
 * Rotate by a compass heading about `origin` (default: the model origin).
 *
 * Rotating a shape to heading θ turns it clockwise by θ in [east, north] space:
 *   e' =  e·cosθ + n·sinθ
 *   n' = -e·sinθ + n·cosθ
 */
export function rotateRing(ring: Ring, headingDegrees: number, origin: PointMeters = [0, 0]): Ring {
  const t = headingDegrees * DEG;
  const cos = Math.cos(t);
  const sin = Math.sin(t);
  const [ox, oy] = origin;
  return ring.map(([x, y]) => {
    const dx = x - ox;
    const dy = y - oy;
    return [ox + dx * cos + dy * sin, oy - dx * sin + dy * cos] as PointMeters;
  });
}

export function scaleRing(
  ring: Ring,
  scale: number | [number, number],
  origin: PointMeters = [0, 0],
): Ring {
  const [sx, sy] = typeof scale === 'number' ? [scale, scale] : scale;
  const [ox, oy] = origin;
  return ring.map(([x, y]) => [ox + (x - ox) * sx, oy + (y - oy) * sy] as PointMeters);
}

export function translateRing(ring: Ring, [dx, dy]: PointMeters): Ring {
  return ring.map(([x, y]) => [x + dx, y + dy] as PointMeters);
}

/** Intersection area of two simple polygons, via exact boolean clipping. */
export function intersectionArea(a: Ring, b: Ring): number {
  if (a.length < 3 || b.length < 3) return 0;
  try {
    /* c8 ignore next */
    const result = polygonClipping.intersection([closeRing(a)] as never, [closeRing(b)] as never);
    let total = 0;
    for (const poly of result) {
      // First ring is the outer boundary; any others are holes.
      poly.forEach((ring, i) => {
        const a2 = area(ring as Ring);
        total += i === 0 ? a2 : -a2;
      });
    }
    return Math.max(0, total);
  } catch {
    // polygon-clipping throws on certain self-intersecting inputs; a failed
    // overlap test should score zero, not crash the whole placement.
    return 0;
  }
}

/**
 * Intersection over union. 1 = identical, 0 = disjoint.
 *
 * Union is derived arithmetically (areaA + areaB − intersection) rather than by
 * a second boolean op: it is exact for simple polygons and avoids a second
 * chance for the clipper to choke on a messy OSM ring.
 */
export function iou(a: Ring, b: Ring): number {
  const areaA = area(a);
  const areaB = area(b);
  if (areaA <= 0 || areaB <= 0) return 0;
  const inter = intersectionArea(a, b);
  const union = areaA + areaB - inter;
  return union > 0 ? inter / union : 0;
}

/** Axis-aligned bounding-box overlap area. Used for the cheap collision test. */
export function bboxOverlapArea(a: Ring, b: Ring): number {
  const ba = bounds(a);
  const bb = bounds(b);
  const w = Math.min(ba.maxX, bb.maxX) - Math.max(ba.minX, bb.minX);
  const d = Math.min(ba.maxY, bb.maxY) - Math.max(ba.minY, bb.minY);
  return w > 0 && d > 0 ? w * d : 0;
}

/**
 * Compass bearing of the polygon's longest edge, folded to [0, 180).
 *
 * A building edge has no inherent direction — bearing 90 and bearing 270
 * describe the same wall — so the fold removes a meaningless distinction. The
 * 180 degree ambiguity it leaves is then resolved by the 0/90/180/270 candidate
 * sweep in the placement search.
 */
export function longestEdgeBearing(ring: Ring): number {
  const r = openRing(ring);
  let best = 0;
  let bestLength = -1;
  for (let i = 0; i < r.length; i++) {
    const a = r[i]!;
    const b = r[(i + 1) % r.length]!;
    const dx = b[0] - a[0];
    const dy = b[1] - a[1];
    const len = Math.hypot(dx, dy);
    if (len > bestLength) {
      bestLength = len;
      // atan2(east, north) -> compass bearing.
      best = ((Math.atan2(dx, dy) * 180) / Math.PI + 360) % 180;
    }
  }
  return best;
}

export interface MinAreaRectangle {
  /** Compass heading of the rectangle's long side, folded to [0, 180). */
  angleDegrees: number;
  /** Extent along the long side. */
  length: number;
  /** Extent across it. */
  width: number;
  area: number;
}

/**
 * Smallest-area enclosing rectangle, by rotating calipers.
 *
 * This is the shape's principal axis, and it is used instead of the longest
 * edge wherever an *orientation* is needed. Measured on the real VT footprints:
 * the min-area-rectangle angle of a building and of its own convex hull agree
 * exactly (Hancock Hall 42.0 vs 42.0 degrees, Campbell Hall 123.8 vs 123.8),
 * while their longest edges disagree by up to 65 degrees — because a hull edge
 * that bridges a concave notch is long but says nothing about how the building
 * is oriented. Since step 08 compares a mesh's convex base outline against a
 * possibly-concave OSM polygon, that stability is the difference between a
 * building landing square on its footprint and landing 29 m away.
 *
 * The minimum-area rectangle always has one side collinear with a hull edge, so
 * testing each hull edge is exact rather than a search.
 */
export function minAreaRectangle(ring: Ring): MinAreaRectangle {
  const hull = openRing(convexHull(openRing(ring)));
  if (hull.length < 3) {
    const b = bounds(ring);
    return { angleDegrees: 0, length: b.width, width: b.depth, area: b.width * b.depth };
  }

  let best: MinAreaRectangle | null = null;

  for (let i = 0; i < hull.length; i++) {
    const a = hull[i]!;
    const b = hull[(i + 1) % hull.length]!;
    const dx = b[0] - a[0];
    const dy = b[1] - a[1];
    if (Math.hypot(dx, dy) < 1e-9) continue;

    // Compass bearing of this edge. rotateRing maps a feature at bearing b to
    // b + theta, so aligning this edge with north takes MINUS its bearing.
    const edgeHeading = (Math.atan2(dx, dy) * 180) / Math.PI;
    const box = bounds(rotateRing(hull, -edgeHeading));
    const boxArea = box.width * box.depth;

    if (!best || boxArea < best.area) {
      const longAlongY = box.depth >= box.width;
      best = {
        // The rotation aligns the edge with north, so the box's north extent
        // lies along that edge; name whichever side is longer as the length.
        angleDegrees: normalizeDegrees(longAlongY ? edgeHeading : edgeHeading + 90) % 180,
        length: Math.max(box.width, box.depth),
        width: Math.min(box.width, box.depth),
        area: boxArea,
      };
    }
  }

  const fallback = bounds(ring);
  return (
    best ?? {
      angleDegrees: 0,
      length: fallback.width,
      width: fallback.depth,
      area: fallback.width * fallback.depth,
    }
  );
}

/** Andrew's monotone chain. Used to turn a cloud of mesh base vertices into an outline. */
export function convexHull(points: PointMeters[]): Ring {
  if (points.length < 3) return [...points];

  const sorted = [...points].sort((p, q) => (p[0] === q[0] ? p[1] - q[1] : p[0] - q[0]));
  const cross = (o: PointMeters, a: PointMeters, b: PointMeters) =>
    (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);

  const build = (pts: PointMeters[]): PointMeters[] => {
    const out: PointMeters[] = [];
    for (const p of pts) {
      while (out.length >= 2 && cross(out[out.length - 2]!, out[out.length - 1]!, p) <= 0) {
        out.pop();
      }
      out.push(p);
    }
    out.pop();
    return out;
  };

  const hull = [...build(sorted), ...build([...sorted].reverse())];
  return hull.length >= 3 ? hull : [...points];
}

// Fail loudly at import time rather than degrading every IoU to zero if the
// clipper ever resolves to something uncallable again.
if (typeof polygonClipping?.intersection !== 'function') {
  throw new Error(
    'polygon-clipping did not resolve to a callable module — IoU scoring would silently return 0.',
  );
}
