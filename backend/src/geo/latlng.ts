/**
 * Geodetic helpers shared by the photo bbox builder (spec 03) and the
 * placement transform (spec 08).
 *
 * Everything here works in a local tangent-plane ("ENU") approximation: pick an
 * anchor lat/lng, convert nearby points to metres east/north of it, do plain
 * Euclidean geometry, convert back. At building scale (tens of metres) the error
 * from ignoring earth curvature is well under a centimetre, and it lets the IoU
 * work in file 08 be ordinary 2D polygon maths.
 */

export interface LatLng {
  lat: number;
  lng: number;
}

/** [east, north] metres relative to a projection anchor. */
export type PointMeters = [number, number];

export interface BBox {
  minLng: number;
  minLat: number;
  maxLng: number;
  maxLat: number;
}

const DEG = Math.PI / 180;

/**
 * Metres per degree of latitude at a given latitude (WGS84 series expansion).
 * Spec 02 explicitly calls out not hardcoding a fixed metres-per-degree.
 */
export function metersPerDegreeLat(lat: number): number {
  const p = lat * DEG;
  return (
    111132.92 -
    559.82 * Math.cos(2 * p) +
    1.175 * Math.cos(4 * p) -
    0.0023 * Math.cos(6 * p)
  );
}

/** Metres per degree of longitude at a given latitude (WGS84 series expansion). */
export function metersPerDegreeLng(lat: number): number {
  const p = lat * DEG;
  return (
    111412.84 * Math.cos(p) - 93.5 * Math.cos(3 * p) + 0.118 * Math.cos(5 * p)
  );
}

/** A bbox roughly `meters` in every direction from a point. Used for Mapillary. */
export function bboxAround(lat: number, lng: number, meters: number): BBox {
  const dLat = meters / metersPerDegreeLat(lat);
  const dLng = meters / metersPerDegreeLng(lat);
  return {
    minLng: lng - dLng,
    minLat: lat - dLat,
    maxLng: lng + dLng,
    maxLat: lat + dLat,
  };
}

/** Mapillary wants `minLng,minLat,maxLng,maxLat` as a bare comma string. */
export function bboxToParam(b: BBox): string {
  return [b.minLng, b.minLat, b.maxLng, b.maxLat]
    .map((n) => n.toFixed(7))
    .join(',');
}

/**
 * A projector fixed to one anchor. Reuse the same instance for the footprint
 * polygon, its neighbours and the placed mesh so they all share one frame.
 */
export class LocalProjection {
  readonly anchor: LatLng;
  private readonly mLat: number;
  private readonly mLng: number;

  constructor(anchor: LatLng) {
    this.anchor = anchor;
    this.mLat = metersPerDegreeLat(anchor.lat);
    this.mLng = metersPerDegreeLng(anchor.lat);
  }

  /** lat/lng -> [east, north] metres from the anchor. */
  toMeters(p: LatLng): PointMeters {
    return [(p.lng - this.anchor.lng) * this.mLng, (p.lat - this.anchor.lat) * this.mLat];
  }

  /** [east, north] metres from the anchor -> lat/lng. */
  toLatLng([east, north]: PointMeters): LatLng {
    return {
      lat: this.anchor.lat + north / this.mLat,
      lng: this.anchor.lng + east / this.mLng,
    };
  }

  ringToMeters(ring: readonly LatLng[]): PointMeters[] {
    return ring.map((p) => this.toMeters(p));
  }
}

/** Great-circle distance in metres. */
export function haversineMeters(a: LatLng, b: LatLng): number {
  const R = 6371008.8;
  const dLat = (b.lat - a.lat) * DEG;
  const dLng = (b.lng - a.lng) * DEG;
  const s =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(a.lat * DEG) * Math.cos(b.lat * DEG) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(s)));
}

/** Compass bearing (0 = north, 90 = east) of the segment a -> b. */
export function bearingDegrees(a: LatLng, b: LatLng): number {
  const y = Math.sin((b.lng - a.lng) * DEG) * Math.cos(b.lat * DEG);
  const x =
    Math.cos(a.lat * DEG) * Math.sin(b.lat * DEG) -
    Math.sin(a.lat * DEG) * Math.cos(b.lat * DEG) * Math.cos((b.lng - a.lng) * DEG);
  return normalizeDegrees((Math.atan2(y, x) * 180) / Math.PI);
}

/** Fold any angle into [0, 360). */
export function normalizeDegrees(deg: number): number {
  return ((deg % 360) + 360) % 360;
}
