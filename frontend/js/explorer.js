// Moon Explorer canvas map. Same projection and terrain colour ramps as Person 3's OpenLayers
// Moon Explorer (original_modules/person3/moon_navigation/src/web/App.tsx), reimplemented without a
// build step. Projected metres: +x east of lon 0 meridian, +y toward lon 0. North-up = +y up.
import { project, unproject, rhoAtLat } from "./geo.js";

const STRATEGY_COLOR = { shortest: "#5aa9ff", balanced: "#f2b84b", gentle: "#4cd08a" }; // Person 3 palette
const BASEMAP_HALF = 150_000;

// ---- Person 3 terrain ramps (copied from App.tsx) ----
const lerp = (a, b, t) => a.map((v, i) => Math.round(v + (b[i] - v) * t));
function elevationColor(t) {
  const stops = [[20, 30, 70], [40, 110, 130], [190, 170, 120], [245, 245, 240]];
  const x = Math.min(0.9999, Math.max(0, t)) * (stops.length - 1); const k = Math.floor(x);
  return lerp(stops[k], stops[k + 1], x - k);
}
function slopeColor(deg, limit = 15) {
  if (deg > limit) return [150, 20, 30];
  const t = deg / limit;
  return t < 0.5 ? lerp([30, 150, 90], [240, 210, 60], t / 0.5) : lerp([240, 210, 60], [225, 70, 50], (t - 0.5) / 0.5);
}

// ---- Illustrative basemap: procedural craters with low-angle polar lighting. Not data. ----
function hash2(x, y) { const s = Math.sin(x * 127.1 + y * 311.7) * 43758.5453; return s - Math.floor(s); }
function craterField(x, y) {
  const ix = Math.floor(x), iy = Math.floor(y); let h = 0;
  for (let j = -1; j <= 1; j++) for (let i = -1; i <= 1; i++) {
    const cx = ix + i, cy = iy + j; const o = hash2(cx, cy);
    if (o < 0.35) continue;
    const ox = hash2(cx + 17.3, cy - 4.1), oy = hash2(cx - 9.7, cy + 31.9);
    const r = 0.16 + 0.3 * hash2(cx + 3.3, cy + 7.7);
    const d = Math.hypot(cx + ox - x, cy + oy - y) / r;
    if (d < 1.6) h += (d < 1 ? (d * d - 1) * 0.55 : 0) + Math.exp(-(((d - 1) * 4) ** 2)) * 0.28;
  }
  return h;
}
function buildBasemap(px = 640) {
  const c = document.createElement("canvas"); c.width = c.height = px;
  const ctx = c.getContext("2d"); const img = ctx.createImageData(px, px);
  const H = new Float32Array(px * px); const m = (2 * BASEMAP_HALF) / px;
  for (let j = 0; j < px; j++) for (let i = 0; i < px; i++) {
    const x = (i * m - BASEMAP_HALF) / 1000, y = (BASEMAP_HALF - j * m) / 1000; // km
    H[j * px + i] = craterField(x / 22, y / 22) * 1.0 + craterField(x / 8, y / 8) * 0.35 + craterField(x / 3, y / 3) * 0.1;
  }
  const L = [-0.8, 0.45, 0.4]; // low sun
  for (let j = 0; j < px; j++) for (let i = 0; i < px; i++) {
    const k = j * px + i;
    const dx = (H[j * px + Math.min(i + 1, px - 1)] - H[j * px + Math.max(i - 1, 0)]) * 9;
    const dy = (H[Math.max(j - 1, 0) * px + i] - H[Math.min(j + 1, px - 1) * px + i]) * 9;
    const n = [-dx, -dy, 1]; const nl = Math.hypot(...n);
    const lam = Math.max(0, (n[0] * L[0] + n[1] * L[1] + n[2] * L[2]) / nl);
    const v = 26 + 120 * lam;
    img.data[k * 4] = v * 0.86; img.data[k * 4 + 1] = v * 0.9; img.data[k * 4 + 2] = v; img.data[k * 4 + 3] = 255;
  }
  ctx.putImageData(img, 0, 0);
  return c;
}

function gridCanvas(g, mode, slopeLimit) {
  const c = document.createElement("canvas"); c.width = g.cols; c.height = g.rows;
  const ctx = c.getContext("2d"); const img = ctx.createImageData(g.cols, g.rows);
  let lo = Infinity, hi = -Infinity; for (const v of g.elevation_m) { if (v < lo) lo = v; if (v > hi) hi = v; }
  for (let j = 0; j < g.rows; j++) for (let i = 0; i < g.cols; i++) {
    const src = j * g.cols + i; const dst = ((g.rows - 1 - j) * g.cols + i) * 4; // rows run south->north by y
    const col = mode === "slope" ? slopeColor(g.slope_deg[src], slopeLimit) : elevationColor((g.elevation_m[src] - lo) / (hi - lo || 1));
    img.data[dst] = col[0]; img.data[dst + 1] = col[1]; img.data[dst + 2] = col[2]; img.data[dst + 3] = 255;
  }
  ctx.putImageData(img, 0, 0);
  return c;
}

export class MoonExplorer {
  constructor(canvas, { onSelect, onPick, onCursor } = {}) {
    this.canvas = canvas; this.ctx = canvas.getContext("2d");
    this.cb = { onSelect, onPick, onCursor };
    this.view = { x: 0, y: 0, mpp: 220 };
    this.layers = { terrain: "elevation", p3Sites: false, basemap: true };
    this.sites = []; this.p3Sites = []; this.grid = null; this.gridImg = null;
    this.route = null; this.selAlt = null; this.destination = null; this.selected = null; this.pickMode = false;
    this.slopeLimit = 15;
    this.basemap = buildBasemap();
    this.css = { w: 1, h: 1 };
    new ResizeObserver(() => this.resize()).observe(canvas);
    this.bind(); this.resize();
  }
  resize() {
    const r = this.canvas.getBoundingClientRect(); const d = Math.min(devicePixelRatio || 1, 2);
    this.css = { w: Math.max(1, r.width), h: Math.max(1, r.height) };
    this.canvas.width = Math.round(this.css.w * d); this.canvas.height = Math.round(this.css.h * d);
    this.ctx.setTransform(d, 0, 0, d, 0, 0); this.render();
  }
  toScreen(x, y) { return [this.css.w / 2 + (x - this.view.x) / this.view.mpp, this.css.h / 2 - (y - this.view.y) / this.view.mpp]; }
  toWorld(sx, sy) { return [this.view.x + (sx - this.css.w / 2) * this.view.mpp, this.view.y - (sy - this.css.h / 2) * this.view.mpp]; }
  zoom(f, sx = this.css.w / 2, sy = this.css.h / 2) {
    const [wx, wy] = this.toWorld(sx, sy);
    this.view.mpp = Math.min(900, Math.max(15, this.view.mpp * f));
    const [nx, ny] = this.toWorld(sx, sy); this.view.x += wx - nx; this.view.y += wy - ny; this.render();
  }
  flyTo(lat, lon, mpp = 90) {
    const { x, y } = project(lat, lon); const from = { ...this.view }; const t0 = performance.now();
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const step = (now) => {
      const t = reduce ? 1 : Math.min(1, (now - t0) / 600); const e = 1 - (1 - t) ** 3;
      this.view = { x: from.x + (x - from.x) * e, y: from.y + (y - from.y) * e, mpp: from.mpp + (mpp - from.mpp) * e };
      this.render(); if (t < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }
  fitSites() {
    const pts = this.sites.map((s) => project(s.lat, s.lon)); if (!pts.length) return;
    const xs = pts.map((p) => p.x), ys = pts.map((p) => p.y);
    const minx = Math.min(...xs, -50_000), maxx = Math.max(...xs, 50_000), miny = Math.min(...ys, -50_000), maxy = Math.max(...ys, 50_000);
    this.view = { x: (minx + maxx) / 2, y: (miny + maxy) / 2,
      mpp: Math.max((maxx - minx) / Math.max(200, this.css.w - 480), (maxy - miny) / Math.max(200, this.css.h - 200)) };
    this.render();
  }
  bind() {
    const c = this.canvas; let drag = null, moved = false;
    c.addEventListener("wheel", (e) => { e.preventDefault(); const r = c.getBoundingClientRect();
      this.zoom(e.deltaY > 0 ? 1.18 : 1 / 1.18, e.clientX - r.left, e.clientY - r.top); }, { passive: false });
    c.addEventListener("pointerdown", (e) => { drag = { x: e.clientX, y: e.clientY, vx: this.view.x, vy: this.view.y }; moved = false; c.setPointerCapture(e.pointerId); });
    c.addEventListener("pointermove", (e) => {
      const r = c.getBoundingClientRect(); const [wx, wy] = this.toWorld(e.clientX - r.left, e.clientY - r.top);
      this.cb.onCursor?.(unproject(wx, wy));
      if (!drag) return; const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      if (Math.hypot(dx, dy) > 3) moved = true;
      this.view.x = drag.vx - dx * this.view.mpp; this.view.y = drag.vy + dy * this.view.mpp; this.render();
    });
    c.addEventListener("pointerup", (e) => {
      const was = drag; drag = null; if (!was || moved) return;
      const r = c.getBoundingClientRect(); const sx = e.clientX - r.left, sy = e.clientY - r.top;
      const hit = this.hitTest(sx, sy);
      if (hit) { this.cb.onSelect?.(hit); return; }
      if (this.pickMode) { const [wx, wy] = this.toWorld(sx, sy); this.cb.onPick?.(unproject(wx, wy)); }
    });
    c.addEventListener("keydown", (e) => {
      const p = 60 * this.view.mpp;
      const k = { "+": () => this.zoom(1 / 1.3), "=": () => this.zoom(1 / 1.3), "-": () => this.zoom(1.3),
        ArrowLeft: () => { this.view.x -= p; }, ArrowRight: () => { this.view.x += p; },
        ArrowUp: () => { this.view.y += p; }, ArrowDown: () => { this.view.y -= p; } }[e.key];
      if (k) { e.preventDefault(); k(); this.render(); }
    });
  }
  hitTest(sx, sy) {
    const all = [...this.sites.map((s) => ({ ...s, layer: "plan" })), ...(this.layers.p3Sites ? this.p3Sites.map((s) => ({ ...s, layer: "p3" })) : [])];
    let best = null, bd = 16;
    for (const s of all) { const p = project(s.lat, s.lon); const [x, y] = this.toScreen(p.x, p.y);
      const d = Math.hypot(x - sx, y - sy); if (d < bd) { bd = d; best = s; } }
    return best;
  }
  setGrid(g) { this.grid = g; this.rebuildGrid(); }
  setTerrainMode(m) { this.layers.terrain = m; this.rebuildGrid(); }
  setSlopeLimit(v) { this.slopeLimit = v; if (this.layers.terrain === "slope") this.rebuildGrid(); }
  rebuildGrid() { this.gridImg = this.grid && this.layers.terrain !== "none" ? gridCanvas(this.grid, this.layers.terrain, this.slopeLimit) : null; this.render(); }

  render() {
    const ctx = this.ctx, { w, h } = this.css; if (!ctx) return;
    ctx.fillStyle = "#070c15"; ctx.fillRect(0, 0, w, h);
    // basemap
    if (this.layers.basemap) {
      const [x0, y0] = this.toScreen(-BASEMAP_HALF, BASEMAP_HALF); const s = (2 * BASEMAP_HALF) / this.view.mpp;
      ctx.globalAlpha = 0.9; ctx.imageSmoothingEnabled = true; ctx.drawImage(this.basemap, x0, y0, s, s); ctx.globalAlpha = 1;
    }
    // Person 3 terrain grid
    if (this.gridImg && this.grid) {
      const g = this.grid, half = g.cell_size_m / 2;
      const minx = g.origin_x_m - half, miny = g.origin_y_m - half;
      const maxx = g.origin_x_m + (g.cols - 1) * g.cell_size_m + half, maxy = g.origin_y_m + (g.rows - 1) * g.cell_size_m + half;
      const [sx, sy] = this.toScreen(minx, maxy); const [ex, ey] = this.toScreen(maxx, miny);
      ctx.globalAlpha = 0.72; ctx.drawImage(this.gridImg, sx, sy, ex - sx, ey - sy); ctx.globalAlpha = 1;
      ctx.strokeStyle = "rgba(213,217,223,.55)"; ctx.setLineDash([5, 5]); ctx.strokeRect(sx, sy, ex - sx, ey - sy); ctx.setLineDash([]);
      ctx.fillStyle = "rgba(213,217,223,.8)"; ctx.font = "11px var(--body, system-ui)";
      ctx.fillText(`Terrain coverage (${g.terrain_source?.data_status ?? g.data_status})`, sx + 6, sy + 14);
    }
    this.graticule();
    // routes
    if (this.route) {
      const alts = [...this.route.alternatives].sort((a, b) => (a.alt_id === this.selAlt) - (b.alt_id === this.selAlt));
      for (const a of alts) {
        const sel = a.alt_id === this.selAlt; ctx.beginPath();
        a.waypoints.forEach((wp, i) => { const p = project(wp.lat_deg, wp.lon_deg); const [x, y] = this.toScreen(p.x, p.y); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
        ctx.strokeStyle = STRATEGY_COLOR[a.strategy] || "#fff"; ctx.lineWidth = sel ? 4.5 : 2;
        ctx.setLineDash(sel ? [] : [8, 6]); ctx.stroke(); ctx.setLineDash([]);
      }
    }
    if (this.destination) {
      const p = project(this.destination.lat_deg, this.destination.lon_deg); const [x, y] = this.toScreen(p.x, p.y);
      ctx.strokeStyle = "#fff"; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(x - 8, y - 8); ctx.lineTo(x + 8, y + 8); ctx.moveTo(x + 8, y - 8); ctx.lineTo(x - 8, y + 8); ctx.stroke();
      this.label("Destination", x + 12, y + 4, "#fff");
    }
    if (this.layers.p3Sites) for (const s of this.p3Sites) this.marker(s, "p3");
    for (const s of this.sites) this.marker(s, "plan");
  }
  graticule() {
    const ctx = this.ctx; const [cx, cy] = this.toScreen(0, 0);
    ctx.strokeStyle = "rgba(105,198,238,.45)"; ctx.lineWidth = 1; ctx.fillStyle = "rgba(105,198,238,.7)"; ctx.font = "11px system-ui";
    for (let lat = -89; lat >= -84; lat--) {
      const r = rhoAtLat(lat) / this.view.mpp; ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.stroke();
      ctx.fillText(`${lat}°`, cx + 4, cy - r - 3);
    }
    const R = rhoAtLat(-84) / this.view.mpp;
    for (let lon = 0; lon < 360; lon += 30) {
      const a = (lon * Math.PI) / 180; const ex = cx + Math.sin(a) * R, ey = cy - Math.cos(a) * R;
      ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(ex, ey); ctx.stroke();
      const lbl = lon > 180 ? `${360 - lon}°W` : lon === 0 || lon === 180 ? `${lon}°` : `${lon}°E`;
      ctx.fillText(lbl, ex + Math.sin(a) * 10 - 10, ey - Math.cos(a) * 10 + 4);
    }
    ctx.fillStyle = "rgba(213,217,223,.9)"; ctx.beginPath(); ctx.arc(cx, cy, 2.5, 0, 7); ctx.fill();
    this.label("South pole", cx + 6, cy + 14, "rgba(213,217,223,.8)");
  }
  marker(s, layer) {
    const ctx = this.ctx; const p = project(s.lat, s.lon); const [x, y] = this.toScreen(p.x, p.y);
    const sel = this.selected && this.selected.id === s.id && this.selected.layer === layer;
    if (layer === "p3") {
      ctx.fillStyle = "#5aa9ff"; ctx.strokeStyle = "#fff"; ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.rect(x - 5, y - 5, 10, 10); ctx.fill(); ctx.stroke();
      this.label(s.id, x + 9, y + 4, "#cfe6ff"); return;
    }
    const color = { recommended: "#F2C35B", feasible: "#69C6EE", rejected: "#F07A6A" }[s.status] || "#ccc";
    if (sel) { ctx.strokeStyle = "rgba(255,255,255,.9)"; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(x, y, 17, 0, 7); ctx.stroke(); }
    ctx.lineWidth = 2.5; ctx.strokeStyle = color; ctx.fillStyle = s.status === "rejected" ? "rgba(7,12,21,.8)" : color;
    ctx.beginPath(); ctx.arc(x, y, s.status === "recommended" ? 9 : 7, 0, 7); ctx.fill(); ctx.stroke();
    if (s.status === "recommended") { ctx.beginPath(); ctx.arc(x, y, 13, 0, 7); ctx.strokeStyle = "rgba(242,195,91,.55)"; ctx.lineWidth = 1.5; ctx.stroke(); }
    this.label(`${s.id}  ${s.name}`, x + 14, y + 4, "#E9ECF0");
  }
  label(t, x, y, color) {
    const ctx = this.ctx; ctx.font = "600 12px system-ui"; ctx.lineJoin = "round"; ctx.lineWidth = 3.5; ctx.strokeStyle = "rgba(7,12,21,.9)";
    ctx.strokeText(t, x, y); ctx.fillStyle = color; ctx.fillText(t, x, y);
  }
}
