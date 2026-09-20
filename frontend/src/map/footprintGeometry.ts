import { metersPerDegree } from "../lib/geo";
import type { Generation } from "../types/contract";

/**
 * The building's footprint rectangle on the ground, in map coordinates.
 *
 * Mesh convention (assets/samples/README.md): the mesh's X axis is the facade's
 * length and points east at yaw 0, with yaw rotating counter-clockwise seen
 * from above. So the width axis has compass bearing `90 - yaw`, and the depth
 * axis is 90 degrees off that.
 */

/** Metres, falling back to a plausible mid-size building when step 08 is silent. */
export const FALLBACK_FOOTPRINT: [number, number] = [26, 18];

export function footprintSize(row: Generation): [number, number] {
  const w = Number(row.placement?.footprintWidthMeters);
  const d = Number(row.placement?.footprintDepthMeters);
  if (!Number.isFinite(w) || !Number.isFinite(d) || w <= 0 || d <= 0) {
    return FALLBACK_FOOTPRINT;
  }
  return [w, d];
}

/** Radius that comfortably encloses the building, for the low-confidence ring. */
export function enclosingRadiusMeters(row: Generation): number {
  const [w, d] = footprintSize(row);
  return 0.5 * Math.hypot(w, d) * 1.12;
}

/** The four ground corners as [lng, lat], rotated to the building's yaw. */
export function footprintCorners(
  row: Generation,
  inflate = 1,
): [number, number][] {
  const lat = Number(row.placement?.position?.[0] ?? row.lat);
  const lng = Number(row.placement?.position?.[1] ?? row.lng);
  const yaw = Number(row.placement?.rotationDegrees ?? 0) || 0;
  const [w, d] = footprintSize(row);
  const [mLat, mLng] = metersPerDegree(lat);

  const rad = (deg: number) => (deg * Math.PI) / 180;
  // Compass bearing -> unit (north, east).
  const widthBearing = 90 - yaw;
  const depthBearing = widthBearing + 90;
  const wN = Math.cos(rad(widthBearing)), wE = Math.sin(rad(widthBearing));
  const dN = Math.cos(rad(depthBearing)), dE = Math.sin(rad(depthBearing));

  const hw = (w / 2) * inflate;
  const hd = (d / 2) * inflate;
  const corners: [number, number][] = [];
  for (const [sw, sd] of [[1, 1], [1, -1], [-1, -1], [-1, 1]] as const) {
    const north = sw * hw * wN + sd * hd * dN;
    const east = sw * hw * wE + sd * hd * dE;
    corners.push([lng + east / mLng, lat + north / mLat]);
  }
  return corners;
}
