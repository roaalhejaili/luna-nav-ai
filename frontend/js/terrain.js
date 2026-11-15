// Terrain engine for the safety simulation and LUNA WALK.
// Grid source: Person 3 GET /terrain/grid?step=1 when the navigation service is online, otherwise the
// bundled snapshot of that same response (data/p3_terrain_fixture.json). Both are Person 3's SYNTHETIC
// fixture (data_status MOCK) until Person 3 loads a real DEM.
// Pathfinding: a line-by-line browser port of Person 3 src/server/pathfinding.ts + routeService.ts
// (same 8-connected A*, same slope blocking, same strategy weights, same distance maths), extended with
// an optional obstacle mask used only by the hazard scenarios.
import { project, unproject, haversineM, MOON_R } from "./geo.js";
import { moonNav } from "./api.js";

export const STRATEGY_WEIGHT = { shortest: 0, balanced: 4, gentle: 24 };

export class Terrain {
  constructor(g, origin) {
    this.cols = g.cols; this.rows = g.rows; this.cell = g.cell_size_m;
    this.ox = g.origin_x_m; this.oy = g.origin_y_m;
    this.elev = Float32Array.from(g.elevation_m);
    this.slope = g.slope_deg ? Float32Array.from(g.slope_deg) : computeSlope(this.elev, g.cols, g.rows, g.cell_size_m);
    this.features = g.named_features || []; this.conversion = g.conversion || null;
    this.source = g.terrain_source; this.status = g.data_status ?? g.terrain_source?.data_status;
    this.origin = origin; // "live" | "snapshot"
    let lo = Infinity, hi = -Infinity; for (const v of this.elev) { if (v < lo) lo = v; if (v > hi) hi = v; }
    this.minE = lo; this.maxE = hi;
  }
  get maxX() { return this.ox + (this.cols - 1) * this.cell; }
  get maxY() { return this.oy + (this.rows - 1) * this.cell; }
  inCoverageXY(x, y) { return x >= this.ox && x <= this.maxX && y >= this.oy && y <= this.maxY; }
  inCoverage(lat, lon) { const p = project(lat, lon); return this.inCoverageXY(p.x, p.y); }
  cellOf(x, y) {
    return { i: Math.min(this.cols - 1, Math.max(0, Math.round((x - this.ox) / this.cell))),
      j: Math.min(this.rows - 1, Math.max(0, Math.round((y - this.oy) / this.cell))) };
  }
  cellCenter(i, j) { return { x: this.ox + i * this.cell, y: this.oy + j * this.cell }; }
  bilinear(field, x, y) {
    const fx = (x - this.ox) / this.cell, fy = (y - this.oy) / this.cell;
    const i0 = Math.min(this.cols - 2, Math.max(0, Math.floor(fx))), j0 = Math.min(this.rows - 2, Math.max(0, Math.floor(fy)));
    const tx = Math.min(1, Math.max(0, fx - i0)), ty = Math.min(1, Math.max(0, fy - j0));
    const v = (i, j) => field[j * this.cols + i];
    return v(i0, j0) * (1 - tx) * (1 - ty) + v(i0 + 1, j0) * tx * (1 - ty) + v(i0, j0 + 1) * (1 - tx) * ty + v(i0 + 1, j0 + 1) * tx * ty;
  }
  heightXY(x, y) { return this.bilinear(this.elev, x, y); }
  slopeXY(x, y) { return this.bilinear(this.slope, x, y); }
  sample(lat, lon) { const p = project(lat, lon); if (!this.inCoverageXY(p.x, p.y)) return null;
    return { elevation_m: this.heightXY(p.x, p.y), slope_deg: this.slopeXY(p.x, p.y), x: p.x, y: p.y }; }

  /** Port of findPath(). blocked: optional Uint8Array mask (1 = impassable), used by hazard scenarios. */
  findPath(start, goal, { maxSlopeDeg, strategy, algorithm = "astar", blocked = null }) {
    const { cols, rows, cell } = this; const w = STRATEGY_WEIGHT[strategy]; const limit = maxSlopeDeg;
    const startIdx = start.j * cols + start.i, goalIdx = goal.j * cols + goal.i;
    const g = new Float64Array(cols * rows).fill(Infinity); const parent = new Int32Array(cols * rows).fill(-1);
    const closed = new Uint8Array(cols * rows); const heap = new MinHeap();
    const h = (idx) => (algorithm === "dijkstra" ? 0 : Math.hypot((idx % cols) - goal.i, ((idx / cols) | 0) - goal.j) * cell);
    const bad = (idx) => this.slope[idx] > limit || (blocked && blocked[idx]);
    g[startIdx] = 0; heap.push(h(startIdx), startIdx);
    const N = [[1, 0, 1], [-1, 0, 1], [0, 1, 1], [0, -1, 1], [1, 1, Math.SQRT2], [1, -1, Math.SQRT2], [-1, 1, Math.SQRT2], [-1, -1, Math.SQRT2]];
    while (heap.size > 0) {
      const cur = heap.pop(); if (closed[cur]) continue; closed[cur] = 1; if (cur === goalIdx) break;
      const ci = cur % cols, cj = (cur / cols) | 0;
      for (const [di, dj, mult] of N) {
        const ni = ci + di, nj = cj + dj; if (ni < 0 || nj < 0 || ni >= cols || nj >= rows) continue;
        const nIdx = nj * cols + ni; if (closed[nIdx]) continue;
        if (nIdx !== goalIdx && bad(nIdx)) continue;
        if (di !== 0 && dj !== 0 && (bad(cj * cols + ni) || bad(nj * cols + ci))) continue;
        const avg = (this.slope[cur] + this.slope[nIdx]) / 2;
        const ng = g[cur] + mult * cell * (1 + w * (avg / limit) ** 2);
        if (ng < g[nIdx]) { g[nIdx] = ng; parent[nIdx] = cur; heap.push(ng + h(nIdx), nIdx); }
      }
    }
    if (!Number.isFinite(g[goalIdx])) return null;
    const cells = []; for (let idx = goalIdx; idx !== -1; idx = parent[idx]) { cells.push({ i: idx % cols, j: (idx / cols) | 0 }); if (idx === startIdx) break; }
    return cells.reverse();
  }
  loc(lat, lon) { const s = this.sample(lat, lon); return { lat_deg: lat, lon_deg: lon, elevation_m: s ? s.elevation_m : null }; }

  /** Port of computeRoutes(): returns the same RouteOutput shape as Person 3 POST /routes, or throws. */
  routes(start, target, maxSlopeDeg, { strategies = ["shortest", "balanced", "gentle"], algorithm = "astar", blocked = null } = {}) {
    const s = project(start.lat_deg, start.lon_deg), t = project(target.lat_deg, target.lon_deg);
    for (const [label, p, src] of [["start", s, start], ["target", t, target]])
      if (!this.inCoverageXY(p.x, p.y)) throw Object.assign(new Error(`OUT_OF_COVERAGE: ${label} point (${src.lat_deg.toFixed(4)}, ${src.lon_deg.toFixed(4)}) is outside the supported terrain coverage.`), { code: "OUT_OF_COVERAGE" });
    const sc = this.cellOf(s.x, s.y), gc = this.cellOf(t.x, t.y);
    const alternatives = [], failed = [];
    for (const strategy of strategies) {
      const cells = this.findPath(sc, gc, { maxSlopeDeg, strategy, algorithm, blocked });
      if (!cells) { failed.push(strategy); continue; }
      const slopes = cells.map((c) => this.slope[c.j * this.cols + c.i]), elevs = cells.map((c) => this.elev[c.j * this.cols + c.i]);
      let gain = 0, loss = 0; for (let k = 1; k < elevs.length; k++) { const d = elevs[k] - elevs[k - 1]; if (d > 0) gain += d; else loss -= d; }
      const simp = simplifyCells(cells);
      const waypoints = simp.map((c, idx) => {
        if (idx === 0) return this.loc(start.lat_deg, start.lon_deg);
        if (idx === simp.length - 1) return this.loc(target.lat_deg, target.lon_deg);
        const { x, y } = this.cellCenter(c.i, c.j); const ll = unproject(x, y); return this.loc(ll.lat_deg, ll.lon_deg);
      });
      const maxSlope = Math.max(...slopes);
      alternatives.push({ alt_id: `${strategy}-${alternatives.length + 1}`, strategy, distance_m: r1(pathDistanceM(waypoints)),
        straight_line_distance_m: r1(haversineM(start, target)), max_slope_deg: Math.round(maxSlope * 100) / 100,
        mean_slope_deg: Math.round((slopes.reduce((a, b) => a + b, 0) / slopes.length) * 100) / 100,
        elevation_gain_m: r1(gain), elevation_loss_m: r1(loss), waypoints, warnings: [] });
    }
    if (!alternatives.length) throw Object.assign(new Error(`NO_ROUTE_FOUND: No route satisfies max_slope_deg=${maxSlopeDeg} between the given points.`), { code: "NO_ROUTE_FOUND", failed });
    return { alternatives, failed, data_status: this.status, operational_validity: "NOT_VALIDATED", engine: "browser port of Person 3 pathfinder" };
  }
  /** Band mask along segment (x1,y1)-(x2,y2) with half-width hw, used for the simulated steep ridge. */
  bandMask(x1, y1, x2, y2, hw, into = null) {
    const m = into || new Uint8Array(this.cols * this.rows); const dx = x2 - x1, dy = y2 - y1, L2 = dx * dx + dy * dy;
    for (let j = 0; j < this.rows; j++) for (let i = 0; i < this.cols; i++) { const c = this.cellCenter(i, j);
      const u = Math.max(0, Math.min(1, ((c.x - x1) * dx + (c.y - y1) * dy) / L2)); if (Math.hypot(c.x - (x1 + u * dx), c.y - (y1 + u * dy)) <= hw) m[j * this.cols + i] = 1; }
    return m;
  }
  /** Circle obstacle mask (projected metres). */
  obstacleMask(x, y, radiusM) {
    const m = new Uint8Array(this.cols * this.rows);
    for (let j = 0; j < this.rows; j++) for (let i = 0; i < this.cols; i++) { const c = this.cellCenter(i, j); if (Math.hypot(c.x - x, c.y - y) <= radiusM) m[j * this.cols + i] = 1; }
    return m;
  }
}
const r1 = (v) => Math.round(v * 10) / 10;
/** Same central-difference slope as Person 3 buildFixtureGrid(). */
function computeSlope(E, n, m, cell) {
  const S = new Float32Array(n * m);
  for (let j = 0; j < m; j++) for (let i = 0; i < n; i++) {
    const im = Math.max(i - 1, 0), ip = Math.min(i + 1, n - 1), jm = Math.max(j - 1, 0), jp = Math.min(j + 1, m - 1);
    const dx = (E[j * n + ip] - E[j * n + im]) / ((ip - im) * cell), dy = (E[jp * n + i] - E[jm * n + i]) / ((jp - jm) * cell);
    S[j * n + i] = (Math.atan(Math.hypot(dx, dy)) * 180) / Math.PI;
  }
  return S;
}
export function pathDistanceM(points) {
  let total = 0;
  for (let k = 1; k < points.length; k++) { const a = points[k - 1], b = points[k];
    const dz = a.elevation_m != null && b.elevation_m != null ? b.elevation_m - a.elevation_m : 0; total += Math.hypot(haversineM(a, b), dz); }
  return total;
}
function simplifyCells(cells) {
  if (cells.length <= 2) return cells; const out = [cells[0]];
  for (let k = 1; k < cells.length - 1; k++) { const a = cells[k - 1], b = cells[k], c = cells[k + 1];
    if (b.i - a.i !== c.i - b.i || b.j - a.j !== c.j - b.j) out.push(b); }
  out.push(cells[cells.length - 1]); return out;
}
class MinHeap {
  constructor() { this.k = []; this.v = []; } get size() { return this.k.length; }
  push(key, val) { const k = this.k, v = this.v; k.push(key); v.push(val); let i = k.length - 1;
    while (i > 0) { const p = (i - 1) >> 1; if (k[p] <= k[i]) break; [k[i], k[p]] = [k[p], k[i]]; [v[i], v[p]] = [v[p], v[i]]; i = p; } }
  pop() { const k = this.k, v = this.v; const top = v[0]; const lk = k.pop(), lv = v.pop();
    if (k.length) { k[0] = lk; v[0] = lv; let i = 0; const n = k.length;
      for (;;) { const l = 2 * i + 1, r = l + 1; let m = i; if (l < n && k[l] < k[m]) m = l; if (r < n && k[r] < k[m]) m = r; if (m === i) break;
        [k[i], k[m]] = [k[m], k[i]]; [v[i], v[m]] = [v[m], v[i]]; i = m; } }
    return top; }
}

/** Load terrain + navigation-module sites. Priority: NASA LOLA grid built by scripts/build_lola_terrain.py,
 *  then Person 3 live grid, then the bundled snapshot of Person 3's fixture. */
export async function loadTerrain() {
  const sitesP = moonNav.sites().catch(() => fetch("data/p3_sites_fixture.json").then((r) => r.json()));
  try {
    const r = await fetch("data/lola_south_pole.json", { cache: "no-cache" });
    if (r.ok) { const g = await r.json(); const s = await sitesP; return { terrain: new Terrain(g, "nasa-lola"), sites: s.sites, sitesMeta: s }; }
  } catch { /* no LOLA grid built yet */ }
  try {
    const [g, s] = await Promise.all([moonNav.grid(1), moonNav.sites()]);
    return { terrain: new Terrain(g, "live"), sites: s.sites, sitesMeta: s };
  } catch {
    const [g, s] = await Promise.all([fetch("data/p3_terrain_fixture.json").then((r) => r.json()), fetch("data/p3_sites_fixture.json").then((r) => r.json())]);
    return { terrain: new Terrain(g, "snapshot"), sites: s.sites, sitesMeta: s };
  }
}
export { MOON_R };
