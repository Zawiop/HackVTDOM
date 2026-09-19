/** Metre-accurate coordinate nudging for step 09's arrow keys.
 *
 * Works in (lat, lng) order, matching `placement.position` and the database
 * columns — note that step 02's footprint geometry is (lng, lat) GeoJSON order.
 */

export function metersPerDegree(lat: number): [number, number] {
  const r = (lat * Math.PI) / 180;
  const mLat = 111132.92 - 559.82 * Math.cos(2 * r) + 1.175 * Math.cos(4 * r);
  const mLng = 111412.84 * Math.cos(r) - 93.5 * Math.cos(3 * r);
  return [mLat, mLng];
}

/** Shift [lat, lng] by a north/east offset in metres. */
export function offsetMeters(
  lat: number,
  lng: number,
  northM: number,
  eastM: number,
): [number, number] {
  const [mLat, mLng] = metersPerDegree(lat);
  return [lat + northM / mLat, lng + eastM / mLng];
}

export function haversineMeters(
  lat1: number,
  lng1: number,
  lat2: number,
  lng2: number,
): number {
  const R = 6371008.8;
  const p1 = (lat1 * Math.PI) / 180;
  const p2 = (lat2 * Math.PI) / 180;
  const dp = p2 - p1;
  const dl = ((lng2 - lng1) * Math.PI) / 180;
  const a =
    Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}
