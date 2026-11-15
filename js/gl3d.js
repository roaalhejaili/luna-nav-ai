// Hand-written WebGL terrain viewer (no Three.js: works offline with no build step).
// Geometry = the terrain grid heights (Person 3 fixture, MOCK) with optional vertical exaggeration.
// Fine surface texture in the shader and the star field / Earth disc are ILLUSTRATIVE only.
import { project, unproject } from "./geo.js";

// ---------- tiny mat4 (column-major) ----------
const M = {
  persp(fovy, a, n, f) { const t = 1 / Math.tan(fovy / 2), nf = 1 / (n - f);
    return [t / a, 0, 0, 0, 0, t, 0, 0, 0, 0, (f + n) * nf, -1, 0, 0, 2 * f * n * nf, 0]; },
  look(e, c, u) {
    let zx = e[0] - c[0], zy = e[1] - c[1], zz = e[2] - c[2]; let l = Math.hypot(zx, zy, zz); zx /= l; zy /= l; zz /= l;
    let xx = u[1] * zz - u[2] * zy, xy = u[2] * zx - u[0] * zz, xz = u[0] * zy - u[1] * zx; l = Math.hypot(xx, xy, xz); xx /= l; xy /= l; xz /= l;
    const yx = zy * xz - zz * xy, yy = zz * xx - zx * xz, yz = zx * xy - zy * xx;
    return [xx, yx, zx, 0, xy, yy, zy, 0, xz, yz, zz, 0, -(xx * e[0] + xy * e[1] + xz * e[2]), -(yx * e[0] + yy * e[1] + yz * e[2]), -(zx * e[0] + zy * e[1] + zz * e[2]), 1]; },
  mul(a, b) { const o = new Array(16); for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) { let s = 0; for (let k = 0; k < 4; k++) s += a[k * 4 + r] * b[c * 4 + k]; o[c * 4 + r] = s; } return o; },
  inv(m) { const [a00, a01, a02, a03, a10, a11, a12, a13, a20, a21, a22, a23, a30, a31, a32, a33] = m;
    const b00 = a00 * a11 - a01 * a10, b01 = a00 * a12 - a02 * a10, b02 = a00 * a13 - a03 * a10, b03 = a01 * a12 - a02 * a11, b04 = a01 * a13 - a03 * a11, b05 = a02 * a13 - a03 * a12,
      b06 = a20 * a31 - a21 * a30, b07 = a20 * a32 - a22 * a30, b08 = a20 * a33 - a23 * a30, b09 = a21 * a32 - a22 * a31, b10 = a21 * a33 - a23 * a31, b11 = a22 * a33 - a23 * a32;
    const d = 1 / (b00 * b11 - b01 * b10 + b02 * b09 + b03 * b08 - b04 * b07 + b05 * b06);
    return [(a11 * b11 - a12 * b10 + a13 * b09) * d, (a02 * b10 - a01 * b11 - a03 * b09) * d, (a31 * b05 - a32 * b04 + a33 * b03) * d, (a22 * b04 - a21 * b05 - a23 * b03) * d,
      (a12 * b08 - a10 * b11 - a13 * b07) * d, (a00 * b11 - a02 * b08 + a03 * b07) * d, (a32 * b02 - a30 * b05 - a33 * b01) * d, (a20 * b05 - a22 * b02 + a23 * b01) * d,
      (a10 * b10 - a11 * b08 + a13 * b06) * d, (a01 * b08 - a00 * b10 - a03 * b06) * d, (a30 * b04 - a31 * b02 + a33 * b00) * d, (a21 * b02 - a20 * b04 - a23 * b00) * d,
      (a11 * b07 - a10 * b09 - a12 * b06) * d, (a00 * b09 - a01 * b07 + a02 * b06) * d, (a31 * b01 - a30 * b03 - a32 * b00) * d, (a20 * b03 - a21 * b01 + a22 * b00) * d]; },
  xf(m, v) { const x = v[0], y = v[1], z = v[2], w = v[3] ?? 1;
    return [m[0] * x + m[4] * y + m[8] * z + m[12] * w, m[1] * x + m[5] * y + m[9] * z + m[13] * w, m[2] * x + m[6] * y + m[10] * z + m[14] * w, m[3] * x + m[7] * y + m[11] * z + m[15] * w]; },
};

const TERRAIN_VS = `attribute vec3 p; attribute vec3 n; attribute vec3 c; uniform mat4 vp; varying vec3 vn; varying vec3 vc; varying vec3 wp;
void main(){ vn=n; vc=c; wp=p; gl_Position=vp*vec4(p,1.); }`;
const TERRAIN_FS = `precision highp float; varying vec3 vn; varying vec3 vc; varying vec3 wp; uniform vec3 sun; uniform vec3 eye; uniform float detail; uniform float fogFar;
float h(vec2 q){ return fract(sin(dot(q,vec2(127.1,311.7)))*43758.5453); }
float vn2(vec2 q){ vec2 i=floor(q), f=fract(q); f=f*f*(3.-2.*f); return mix(mix(h(i),h(i+vec2(1,0)),f.x),mix(h(i+vec2(0,1)),h(i+vec2(1,1)),f.x),f.y); }
void main(){
  vec3 N=normalize(vn); float lam=max(dot(N,sun),0.);
  float tex = detail>0. ? (vn2(wp.xz/detail)*.5+vn2(wp.xz/(detail*.23))*.3+vn2(wp.xz/(detail*.051))*.2) : .5;
  vec3 col=vc*(.80+.40*tex)*(lam*1.15+.07);
  float d=length(wp-eye); float fog=clamp(d/fogFar,0.,1.);
  gl_FragColor=vec4(mix(col, vec3(.02,.03,.05), fog*fog*.85),1.);
}`;
const FLAT_VS = `attribute vec3 p; attribute vec4 c; uniform mat4 vp; uniform float ps; varying vec4 vc; void main(){ vc=c; gl_Position=vp*vec4(p,1.); gl_PointSize=ps; }`;
const FLAT_FS = `precision mediump float; varying vec4 vc; void main(){ gl_FragColor=vc; }`;

function slopeCol(d, lim) { if (d > lim) return [0.59, 0.08, 0.12]; const t = d / lim;
  const L = (a, b, u) => a.map((v, i) => v + (b[i] - v) * u);
  return t < 0.5 ? L([0.12, 0.59, 0.35], [0.94, 0.82, 0.24], t / 0.5) : L([0.94, 0.82, 0.24], [0.88, 0.27, 0.2], (t - 0.5) / 0.5); }
function elevCol(t) { const s = [[0.08, 0.12, 0.27], [0.16, 0.43, 0.51], [0.75, 0.67, 0.47], [0.96, 0.96, 0.94]];
  const x = Math.min(0.9999, Math.max(0, t)) * 3, k = Math.floor(x), u = x - k; return s[k].map((v, i) => v + (s[k + 1][i] - v) * u); }

export class TerrainView {
  constructor(canvas, overlay, { onPick, onModeChange } = {}) {
    this.canvas = canvas; this.overlay = overlay; this.cb = { onPick, onModeChange };
    const gl = canvas.getContext("webgl", { antialias: true }); this.gl = gl; if (!gl) throw new Error("WebGL unavailable");
    gl.getExtension("OES_element_index_uint");
    this.pT = this.prog(TERRAIN_VS, TERRAIN_FS); this.pF = this.prog(FLAT_VS, FLAT_FS);
    this.mode = "orbit"; this.exag = 3; this.colorMode = "regolith"; this.slopeLimit = 15;
    this.orbit = { tx: 0, tz: 0, yaw: 0.6, pitch: 0.75, dist: 95000 };
    this.walk = { x: 0, z: 0, yaw: 0, pitch: -0.05, speed: 6 };
    this.paths = []; this.markers = []; this.rings = []; this.keys = new Set(); this.dirty = true;
    this.stars = this.makeStars();
    this.bind(); new ResizeObserver(() => { this.resize(); }).observe(canvas); this.resize();
    const loop = () => { this.step(); if (this.dirty) { this.draw(); this.dirty = false; } this.raf = requestAnimationFrame(loop); };
    this.raf = requestAnimationFrame(loop);
  }
  prog(vs, fs) { const gl = this.gl; const mk = (t, s) => { const o = gl.createShader(t); gl.shaderSource(o, s); gl.compileShader(o);
      if (!gl.getShaderParameter(o, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(o)); return o; };
    const p = gl.createProgram(); gl.attachShader(p, mk(gl.VERTEX_SHADER, vs)); gl.attachShader(p, mk(gl.FRAGMENT_SHADER, fs)); gl.linkProgram(p); return p; }
  resize() { const d = Math.min(devicePixelRatio || 1, 2), r = this.canvas.getBoundingClientRect();
    this.w = Math.max(1, r.width); this.h = Math.max(1, r.height); this.canvas.width = Math.round(this.w * d); this.canvas.height = Math.round(this.h * d); this.dirty = true; }

  // ---------- data ----------
  setTerrain(t) { this.t = t; this.buildMesh(); if (!this.walkPlaced) { this.orbit.tx = 0; this.orbit.tz = 0; this.orbit.dist = Math.max(95000, (t.maxX - t.ox) * 1.05); } this.dirty = true; }
  setExaggeration(e) { this.exag = e; this.buildMesh(); this.rebuildOverlays(); }
  setColorMode(m, lim = this.slopeLimit) { this.colorMode = m; this.slopeLimit = lim; this.buildMesh(); }
  hY(x, y) { return (this.t.heightXY(x, y) - this.t.minE) * this.ex(); }
  ex() { return this.mode === "walk" ? 1 : this.exag; }
  world(lat, lon, lift = 0) { const p = project(lat, lon); return [p.x, this.t ? this.hY(p.x, p.y) + lift : 0, -p.y]; }
  buildMesh() {
    const t = this.t, gl = this.gl; if (!t) return; const C = t.cols, R = t.rows, E = this.ex();
    const pos = new Float32Array(C * R * 3), nor = new Float32Array(C * R * 3), col = new Float32Array(C * R * 3);
    const H = (i, j) => (t.elev[Math.min(R - 1, Math.max(0, j)) * C + Math.min(C - 1, Math.max(0, i))] - t.minE) * E;
    for (let j = 0; j < R; j++) for (let i = 0; i < C; i++) {
      const k = j * C + i, x = t.ox + i * t.cell, y = t.oy + j * t.cell;
      pos.set([x, H(i, j), -y], k * 3);
      const dx = (H(i + 1, j) - H(i - 1, j)) / (2 * t.cell), dy = (H(i, j + 1) - H(i, j - 1)) / (2 * t.cell);
      const n = [-dx, 1, dy], l = Math.hypot(...n); nor.set([n[0] / l, n[1] / l, n[2] / l], k * 3);
      const c = this.colorMode === "slope" ? slopeCol(t.slope[k], this.slopeLimit) : this.colorMode === "elevation" ? elevCol((t.elev[k] - t.minE) / (t.maxE - t.minE || 1)) : [0.62, 0.63, 0.66];
      col.set(c, k * 3);
    }
    const idx = new Uint32Array((C - 1) * (R - 1) * 6); let q = 0;
    for (let j = 0; j < R - 1; j++) for (let i = 0; i < C - 1; i++) { const a = j * C + i, b = a + 1, c2 = a + C, d = c2 + 1; idx.set([a, c2, b, b, c2, d], q); q += 6; }
    const mk = (data, type = gl.ARRAY_BUFFER) => { const b = gl.createBuffer(); gl.bindBuffer(type, b); gl.bufferData(type, data, gl.STATIC_DRAW); return b; };
    for (const b of [this.mesh?.p, this.mesh?.n, this.mesh?.c, this.mesh?.i]) b && gl.deleteBuffer(b);
    this.mesh = { p: mk(pos), n: mk(nor), c: mk(col), i: mk(idx, gl.ELEMENT_ARRAY_BUFFER), count: idx.length };
    this.rebuildOverlays();
  }
  /** paths: [{ points:[{lat_deg,lon_deg}], color:[r,g,b,a], width_m }] */
  setPaths(paths) { this.paths = paths; this.rebuildOverlays(); }
  /** markers: [{ id, lat, lon, label, color:"#hex", kind }] */
  setMarkers(markers) { this.markers = markers; this.rebuildOverlays(); }
  setRings(rings) { this.rings = rings; this.rebuildOverlays(); }
  rebuildOverlays() {
    if (!this.t) return; const walk = this.mode === "walk", tris = [], lines = [];
    const lift = walk ? 0.35 : 30 * this.exag;
    const ribbon = (pts, color, width) => {
      const dense = [];
      for (let k = 0; k < pts.length - 1; k++) { const a = project(pts[k].lat_deg, pts[k].lon_deg), b = project(pts[k + 1].lat_deg, pts[k + 1].lon_deg);
        const n = Math.max(1, Math.ceil(Math.hypot(b.x - a.x, b.y - a.y) / (walk ? 40 : 200)));
        for (let s = 0; s < n; s++) { const u = s / n; dense.push({ x: a.x + (b.x - a.x) * u, y: a.y + (b.y - a.y) * u }); } }
      const last = pts[pts.length - 1]; if (last) { const p = project(last.lat_deg, last.lon_deg); dense.push(p); }
      for (let k = 0; k < dense.length - 1; k++) { const a = dense[k], b = dense[k + 1]; let dx = b.x - a.x, dy = b.y - a.y; const l = Math.hypot(dx, dy) || 1; const nx = (-dy / l) * width / 2, ny = (dx / l) * width / 2;
        const v = (p, s) => [p.x + nx * s, this.t.inCoverageXY(p.x, p.y) ? this.hY(p.x, p.y) + lift : lift, -(p.y + ny * s), ...color];
        tris.push(...v(a, 1), ...v(a, -1), ...v(b, 1), ...v(b, 1), ...v(a, -1), ...v(b, -1)); }
    };
    const wscale = walk ? 1 : Math.max(1, this.orbit.dist / 60000);
    for (const p of this.paths) if (p.points?.length > 1) ribbon(p.points, p.color, (walk ? p.walkWidth ?? 2.5 : p.width_m ?? 260) * wscale);
    for (const r of this.rings) { const pts = []; for (let a = 0; a <= 64; a++) { const th = (a / 64) * Math.PI * 2; pts.push(unproject(r.x + Math.cos(th) * r.radius_m, r.y + Math.sin(th) * r.radius_m)); }
      ribbon(pts, r.color, (walk ? 6 : 220) * wscale); }
    for (const m of this.markers) { const [x, y, z] = this.world(m.lat, m.lon); const c = hexA(m.color); const top = walk ? 25 : 2600 * Math.max(1, this.orbit.dist / 80000);
      lines.push(x, y, z, ...c, x, y + top, z, ...c); m._top = [x, y + top, z]; m._base = [x, y, z]; }
    const gl = this.gl; const up = (arr, old) => { old && gl.deleteBuffer(old); const b = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(arr), gl.STATIC_DRAW); return b; };
    this.ovTri = up(tris, this.ovTri); this.ovTriN = tris.length / 7; this.ovLin = up(lines, this.ovLin); this.ovLinN = lines.length / 7;
    this.dirty = true;
  }
  makeStars() { const a = []; let s = 11; const r = () => ((s = (s * 16807) % 2147483647) / 2147483647);
    for (let i = 0; i < 1500; i++) { const u = r() * 2 - 1, th = r() * Math.PI * 2, q = Math.sqrt(1 - u * u); const b = 0.35 + r() * 0.65;
      a.push(q * Math.cos(th), Math.abs(u) * 0.9 + 0.02, q * Math.sin(th), b, b, b * 1.05, 1); }
    const gl = this.gl, buf = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buf); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(a), gl.STATIC_DRAW); return { buf, n: a.length / 7 }; }

  // ---------- camera ----------
  setMode(mode, at) {
    this.mode = mode; this.buildMesh();
    if (mode === "walk" && at) { const p = project(at.lat, at.lon); this.walk.x = p.x; this.walk.z = -p.y; this.walk.yaw = at.yaw ?? 0; this.walk.pitch = -0.04; this.walkPlaced = true; }
    this.cb.onModeChange?.(mode); this.dirty = true;
  }
  flyTo(lat, lon, dist = 30000) { const p = project(lat, lon); const from = { ...this.orbit }, to = { tx: p.x, tz: -p.y, dist }; const t0 = performance.now();
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    this.anim = (now) => { const u = reduce ? 1 : Math.min(1, (now - t0) / 800), e = 1 - (1 - u) ** 3;
      this.orbit.tx = from.tx + (to.tx - from.tx) * e; this.orbit.tz = from.tz + (to.tz - from.tz) * e; this.orbit.dist = from.dist + (to.dist - from.dist) * e;
      if (u >= 1) this.anim = null; }; }
  eyeAndCenter() {
    if (this.mode === "walk") { const w = this.walk; const gy = this.t ? this.hY(w.x, -w.z) : 0; const eye = [w.x, gy + 1.7, w.z];
      return { eye, center: [eye[0] + Math.sin(w.yaw) * Math.cos(w.pitch), eye[1] + Math.sin(w.pitch), eye[2] - Math.cos(w.yaw) * Math.cos(w.pitch)] }; }
    const o = this.orbit; const cy = this.t ? this.hY(o.tx, -o.tz) : 0;
    const eye = [o.tx + o.dist * Math.cos(o.pitch) * Math.sin(o.yaw), cy + o.dist * Math.sin(o.pitch), o.tz + o.dist * Math.cos(o.pitch) * Math.cos(o.yaw)];
    return { eye, center: [o.tx, cy, o.tz] };
  }
  matrices() { const { eye, center } = this.eyeAndCenter(); const walk = this.mode === "walk";
    const P = M.persp(walk ? 1.05 : 0.8, this.w / this.h, walk ? 0.4 : Math.max(50, this.orbit.dist / 400), walk ? 90000 : this.orbit.dist * 6 + 200000);
    const V = M.look(eye, center, [0, 1, 0]); return { P, V, VP: M.mul(P, V), eye }; }
  step() {
    if (this.anim) { this.anim(performance.now()); this.rebuildOverlaysThrottled(); this.dirty = true; }
    if (this.mode !== "walk" || !this.keys.size || !this.t) return;
    const w = this.walk, fast = this.keys.has("shift") ? 5 : 1, v = w.speed * fast * (1 / 60) * 20;
    let fx = 0, fz = 0; const f = [Math.sin(w.yaw), -Math.cos(w.yaw)], r = [Math.cos(w.yaw), Math.sin(w.yaw)];
    if (this.keys.has("w") || this.keys.has("arrowup")) { fx += f[0]; fz += f[1]; } if (this.keys.has("s") || this.keys.has("arrowdown")) { fx -= f[0]; fz -= f[1]; }
    if (this.keys.has("d")) { fx += r[0]; fz += r[1]; } if (this.keys.has("a")) { fx -= r[0]; fz -= r[1]; }
    if (this.keys.has("arrowleft")) w.yaw -= 0.03; if (this.keys.has("arrowright")) w.yaw += 0.03;
    const nx = w.x + fx * v, nz = w.z + fz * v; if (this.t.inCoverageXY(nx, -nz)) { w.x = nx; w.z = nz; }
    this.dirty = true; this.cb.onWalk?.(unproject(w.x, -w.z));
  }
  rebuildOverlaysThrottled() { const now = performance.now(); if (!this._rb || now - this._rb > 120) { this._rb = now; this.rebuildOverlays(); } }

  // ---------- input ----------
  bind() {
    const c = this.canvas; let drag = null;
    c.addEventListener("contextmenu", (e) => e.preventDefault());
    c.addEventListener("pointerdown", (e) => { drag = { x: e.clientX, y: e.clientY, b: e.button, shift: e.shiftKey, moved: false }; c.setPointerCapture(e.pointerId); c.focus(); });
    c.addEventListener("pointermove", (e) => { if (!drag) return; const dx = e.clientX - drag.x, dy = e.clientY - drag.y; if (Math.hypot(dx, dy) > 3) drag.moved = true; drag.x = e.clientX; drag.y = e.clientY;
      if (this.mode === "walk") { this.walk.yaw += dx * 0.004; this.walk.pitch = Math.max(-1.2, Math.min(1.2, this.walk.pitch - dy * 0.004)); }
      else if (drag.b === 2 || drag.shift) { const o = this.orbit, s = o.dist / this.h * 1.3; const cs = Math.cos(o.yaw), sn = Math.sin(o.yaw);
        o.tx += (-dx * cs - dy * sn) * s; o.tz += (dx * sn - dy * cs) * s; this.clampTarget(); }
      else { this.orbit.yaw -= dx * 0.006; this.orbit.pitch = Math.max(0.12, Math.min(1.5, this.orbit.pitch + dy * 0.005)); }
      this.dirty = true; });
    c.addEventListener("pointerup", (e) => { const d = drag; drag = null; if (d && !d.moved && d.b === 0) { const hit = this.pick(e.clientX, e.clientY); if (hit) this.cb.onPick?.(hit); } });
    c.addEventListener("wheel", (e) => { e.preventDefault(); if (this.mode === "walk") { this.walk.speed = Math.max(1, Math.min(60, this.walk.speed * (e.deltaY > 0 ? 0.85 : 1.15))); return; }
      this.orbit.dist = Math.max(2500, Math.min(260000, this.orbit.dist * (e.deltaY > 0 ? 1.15 : 1 / 1.15))); this.rebuildOverlaysThrottled(); this.dirty = true; }, { passive: false });
    c.addEventListener("keydown", (e) => { const k = e.key.toLowerCase(); if (["w", "a", "s", "d", "arrowup", "arrowdown", "arrowleft", "arrowright", "shift"].includes(k)) { this.keys.add(k); e.preventDefault(); }
      if (this.mode !== "walk") { const o = this.orbit; if (k === "+" || k === "=") o.dist /= 1.25; if (k === "-") o.dist *= 1.25; if (k === "arrowleft") o.yaw += 0.08; if (k === "arrowright") o.yaw -= 0.08;
        if (k === "arrowup") o.pitch = Math.min(1.5, o.pitch + 0.06); if (k === "arrowdown") o.pitch = Math.max(0.12, o.pitch - 0.06); this.rebuildOverlaysThrottled(); this.dirty = true; } });
    c.addEventListener("keyup", (e) => this.keys.delete(e.key.toLowerCase()));
    c.addEventListener("blur", () => this.keys.clear());
  }
  clampTarget() { const o = this.orbit, L = 160000; o.tx = Math.max(-L, Math.min(L, o.tx)); o.tz = Math.max(-L, Math.min(L, o.tz)); }
  /** Ray-march the terrain surface. Returns { lat_deg, lon_deg } or null. */
  pick(cx, cy) {
    if (!this.t) return null; const r = this.canvas.getBoundingClientRect(); const nx = ((cx - r.left) / this.w) * 2 - 1, ny = 1 - ((cy - r.top) / this.h) * 2;
    const { VP } = this.matrices(); const inv = M.inv(VP); const a = M.xf(inv, [nx, ny, -1, 1]), b = M.xf(inv, [nx, ny, 1, 1]);
    const p0 = [a[0] / a[3], a[1] / a[3], a[2] / a[3]], p1 = [b[0] / b[3], b[1] / b[3], b[2] / b[3]]; const d = [p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]]; const L = Math.hypot(...d);
    const step = this.mode === "walk" ? 5 : Math.max(40, this.orbit.dist / 600); let prev = null;
    for (let s = 0; s < Math.min(L, 400000); s += step) { const x = p0[0] + (d[0] / L) * s, y = p0[1] + (d[1] / L) * s, z = p0[2] + (d[2] / L) * s;
      if (!this.t.inCoverageXY(x, -z)) { prev = null; continue; } if (y <= this.hY(x, -z)) return unproject(x, -z); prev = [x, y, z]; }
    return null;
  }
  screenOf(v, VP) { const c = M.xf(VP, [v[0], v[1], v[2], 1]); if (c[3] <= 0) return null; return [((c[0] / c[3]) * 0.5 + 0.5) * this.w, (1 - ((c[1] / c[3]) * 0.5 + 0.5)) * this.h, c[3]]; }

  // ---------- draw ----------
  draw() {
    const gl = this.gl; gl.viewport(0, 0, this.canvas.width, this.canvas.height);
    gl.clearColor(0.012, 0.018, 0.035, 1); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT); gl.enable(gl.DEPTH_TEST);
    const { V, P, VP, eye } = this.matrices(); const walk = this.mode === "walk";
    for (let i = 0; i < 8; i++) gl.disableVertexAttribArray(i);
    // stars: rotation-only view
    const Vr = V.slice(); Vr[12] = Vr[13] = Vr[14] = 0; const VPr = M.mul(P, Vr); const starScale = 1000;
    gl.useProgram(this.pF); gl.depthMask(false);
    gl.uniformMatrix4fv(gl.getUniformLocation(this.pF, "vp"), false, M.mul(VPr, [starScale, 0, 0, 0, 0, starScale, 0, 0, 0, 0, starScale, 0, 0, 0, 0, 1]));
    gl.uniform1f(gl.getUniformLocation(this.pF, "ps"), 1.6); this.attrs(this.pF, this.stars.buf, true); gl.drawArrays(gl.POINTS, 0, this.stars.n); gl.depthMask(true);
    if (!this.mesh) return;
    for (let i = 0; i < 8; i++) gl.disableVertexAttribArray(i);
    gl.useProgram(this.pT); gl.uniformMatrix4fv(gl.getUniformLocation(this.pT, "vp"), false, VP);
    const sun = [0.82, 0.2, 0.53], sl = Math.hypot(...sun); gl.uniform3f(gl.getUniformLocation(this.pT, "sun"), sun[0] / sl, sun[1] / sl, sun[2] / sl);
    gl.uniform3fv(gl.getUniformLocation(this.pT, "eye"), eye); gl.uniform1f(gl.getUniformLocation(this.pT, "detail"), walk ? 30 : 2500);
    gl.uniform1f(gl.getUniformLocation(this.pT, "fogFar"), walk ? 45000 : this.orbit.dist * 4);
    const bindA = (prog, name, buf, size) => { const l = gl.getAttribLocation(prog, name); gl.bindBuffer(gl.ARRAY_BUFFER, buf); gl.enableVertexAttribArray(l); gl.vertexAttribPointer(l, size, gl.FLOAT, false, 0, 0); };
    bindA(this.pT, "p", this.mesh.p, 3); bindA(this.pT, "n", this.mesh.n, 3); bindA(this.pT, "c", this.mesh.c, 3);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.mesh.i); gl.drawElements(gl.TRIANGLES, this.mesh.count, gl.UNSIGNED_INT, 0);
    // overlays
    for (let i = 0; i < 8; i++) gl.disableVertexAttribArray(i);
    gl.useProgram(this.pF); gl.uniformMatrix4fv(gl.getUniformLocation(this.pF, "vp"), false, VP); gl.uniform1f(gl.getUniformLocation(this.pF, "ps"), 1);
    gl.enable(gl.BLEND); gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    gl.enable(gl.POLYGON_OFFSET_FILL); gl.polygonOffset(-2, -2);
    if (this.ovTriN) { this.attrs(this.pF, this.ovTri, true); gl.drawArrays(gl.TRIANGLES, 0, this.ovTriN); }
    gl.disable(gl.POLYGON_OFFSET_FILL);
    if (this.ovLinN) { this.attrs(this.pF, this.ovLin, true); gl.drawArrays(gl.LINES, 0, this.ovLinN); }
    gl.disable(gl.BLEND);
    this.labels(VP);
  }
  attrs(prog, buf) { const gl = this.gl; gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    const p = gl.getAttribLocation(prog, "p"), c = gl.getAttribLocation(prog, "c");
    gl.enableVertexAttribArray(p); gl.vertexAttribPointer(p, 3, gl.FLOAT, false, 28, 0); gl.enableVertexAttribArray(c); gl.vertexAttribPointer(c, 4, gl.FLOAT, false, 28, 12); }
  labels(VP) {
    if (!this.overlay) return; const frag = [], placed = [];
    const items = [];
    for (const m of this.markers) { if (!m._top) continue; const s = this.screenOf(this.mode === "walk" ? m._base.map((v, i) => (i === 1 ? v + 4 : v)) : m._top, VP);
      if (!s || s[0] < -50 || s[0] > this.w + 50 || s[1] < -20 || s[1] > this.h + 20) continue; items.push({ m, s }); }
    items.sort((a, b) => (a.m.kind === "plan" ? -1 : 0) - (b.m.kind === "plan" ? -1 : 0) || a.s[1] - b.s[1]);
    for (const { m, s } of items) {
      let y = s[1]; const w = 14 + String(m.label).replace(/<[^>]+>/g, "").length * 7;
      for (let guard = 0; guard < 8; guard++) { const hit = placed.find((p) => Math.abs(p.y - y) < 17 && s[0] < p.x + p.w && s[0] + w > p.x); if (!hit) break; y = hit.y + 17; }
      placed.push({ x: s[0], y, w });
      const far = this.mode === "walk" ? ` <small>${(s[2] / 1000).toFixed(1)} km</small>` : "";
      frag.push(`<div class="glabel ${m.kind || ""}" style="transform:translate(${s[0].toFixed(0)}px,${y.toFixed(0)}px);--mc:${m.color}"><i></i>${m.label}${far}</div>`); }
    this.overlay.innerHTML = frag.join("");
  }
}
function hexA(h, a = 1) { const n = parseInt(h.replace("#", ""), 16); return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255, a]; }
export { hexA };
