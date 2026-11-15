import { MOON_RADIUS_M } from "../shared/types.js";

const D2R = Math.PI / 180;
const R2D = 180 / Math.PI;

export function normalizeLon(lonDeg: number): number {
  let l = ((lonDeg + 180) % 360 + 360) % 360 - 180;
  if (l === -180 && lonDeg > 0) l = 180;
  return l;
}

/**
 * South-polar stereographic projection on the lunar sphere (R = 1 737 400 m),
 * true scale at the pole, central meridian 0 deg. Equivalent to PROJ:
 * +proj=stere +lat_0=-90 +lat_ts=-90 +lon_0=0 +k=1 +x_0=0 +y_0=0 +R=1737400
 * Returns planar meters (x east-ish, y toward lon 0).
 */
export function projectSouthPolar(latDeg: number, lonDeg: number): { x: number; y: number } {
  const c = (latDeg + 90) * D2R; // angular distance from the south pole
  const rho = 2 * MOON_RADIUS_M * Math.tan(c / 2);
  const lam = lonDeg * D2R;
  return { x: rho * Math.sin(lam), y: rho * Math.cos(lam) };
}

export function unprojectSouthPolar(x: number, y: number): { lat_deg: number; lon_deg: number } {
  const rho = Math.hypot(x, y);
  const c = 2 * Math.atan(rho / (2 * MOON_RADIUS_M));
  const lat = -90 + c * R2D;
  const lon = rho === 0 ? 0 : normalizeLon(Math.atan2(x, y) * R2D);
  return { lat_deg: lat, lon_deg: lon };
}

/** Great-circle distance on the lunar sphere, meters (haversine). */
export function greatCircleDistanceM(
  lat1: number,
  lon1: number,
  lat2: number,
  lon2: number,
): number {
  const p1 = lat1 * D2R;
  const p2 = lat2 * D2R;
  const dp = p2 - p1;
  const dl = (lon2 - lon1) * D2R;
  const a = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * MOON_RADIUS_M * Math.asin(Math.min(1, Math.sqrt(a)));
}
