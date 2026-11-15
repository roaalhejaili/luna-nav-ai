// South-polar stereographic on the lunar sphere, identical to Person 3 src/server/geo.ts and its
// PROJ string: +proj=stere +lat_0=-90 +lat_ts=-90 +lon_0=0 +k=1 +R=1737400
export const MOON_R = 1_737_400;
const D2R = Math.PI / 180, R2D = 180 / Math.PI;

export function lon180(lon) {
  let l = (((lon + 180) % 360) + 360) % 360 - 180;
  if (l === -180 && lon > 0) l = 180;
  return l;
}
export function project(latDeg, lonDeg) {
  const c = (latDeg + 90) * D2R;
  const rho = 2 * MOON_R * Math.tan(c / 2);
  const lam = lonDeg * D2R;
  return { x: rho * Math.sin(lam), y: rho * Math.cos(lam) };
}
export function unproject(x, y) {
  const rho = Math.hypot(x, y);
  const c = 2 * Math.atan(rho / (2 * MOON_R));
  return { lat_deg: -90 + c * R2D, lon_deg: rho === 0 ? 0 : lon180(Math.atan2(x, y) * R2D) };
}
export const rhoAtLat = (lat) => 2 * MOON_R * Math.tan(((lat + 90) * D2R) / 2);
export function haversineM(a, b) {
  const p1 = a.lat_deg * D2R, p2 = b.lat_deg * D2R;
  const dp = p2 - p1, dl = (b.lon_deg - a.lon_deg) * D2R;
  const h = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * MOON_R * Math.asin(Math.min(1, Math.sqrt(h)));
}
