import { CONFIG } from "./config.js";
import { planner, moonNav, ApiError, recordedRuns, REPO_URL } from "./api.js";
import { mountMoon } from "./moon.js";
import { MoonExplorer } from "./explorer.js";
import { TerrainView } from "./gl3d.js";
import { loadTerrain } from "./terrain.js";
import { simulate, defaultStops, snapToTraversable, DEFAULT_ASSUMPTIONS, SCENARIOS } from "./safety.js";
import { mountCabin } from "./cabin.js";
import { lon180, project, unproject, haversineM } from "./geo.js";

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const S = {
  phase: "cabin", plan: null, replanMode: false, lastReq: null, busy: false, sel: null,
  navOnline: false, terrain: null, p3Sites: [], p3Meta: null, route: null, selAlt: null, dest: null, compare: null,
  viewMode: "3d", pick: null, inspect: null,
  stops: null, customStops: {}, assumptions: structuredClone(DEFAULT_ASSUMPTIONS), scenarios: {}, sim: null, simKey: null,
};

/* ================= utilities ================= */
const h1 = (v) => `${Number(v).toFixed(1)} h`;
const pct = (v) => `${Math.round(v * 100)}%`;
const latS = (lat) => `${Math.abs(lat).toFixed(3)}° ${lat < 0 ? "S" : "N"}`;
const lonE = (lon) => { const l = lon180(lon); return `${Math.abs(l).toFixed(2)}° ${l < 0 ? "W" : "E"}`; };
const fmtM = (m) => (m >= 1000 ? `${(m / 1000).toFixed(2)} km` : `${Math.round(m)} m`);
const utc = (iso) => new Date(iso).toLocaleString("en-GB", { timeZone: "UTC", day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) + " UTC";
const day = (iso) => new Date(iso).toLocaleDateString("en-GB", { timeZone: "UTC", day: "numeric", month: "short" });
const statusOf = (s) => (s === "REAL" ? "UNVERIFIED" : s === "PARTIAL" ? "UNVERIFIED" : s);
const badge = (status) => `<span class="badge ${esc(status)}" title="${status === "VERIFIED" ? "Source reports verified data" : status === "MOCK" ? "Synthetic fixture values, not measurements" : "Supplier claim not independently verified"}">${{ MOCK: "Mock data", UNVERIFIED: "Unverified", VERIFIED: "Verified by source" }[status] || esc(status)}</span>`;
const isLola = (t) => t?.origin === "nasa-lola";
const tBadge = (t) => (isLola(t) ? `<span class="badge NASA" title="Measured by the LRO Lunar Orbiter Laser Altimeter; gridded NASA PDS product. Not validated by this team for flight operations.">NASA LOLA data</span>` : badge(statusOf(t?.status)));
const tOrigin = (t) => (isLola(t) ? "NASA LOLA grid built locally from the PDS file" : t?.origin === "live" ? "live from the navigation module" : "bundled snapshot of the navigation module fixture");
const optKey = (o) => `${o.site.site_id}|${o.visibility.date_utc}`;
function toast(msg, ms = 4200) { const t = $("#toast"); t.textContent = msg; t.hidden = false; clearTimeout(toast.t); toast.t = setTimeout(() => (t.hidden = true), ms); }
function utilities(o, req) {
  const s = o.site, v = o.visibility, r = o.route, d = req.duration_hours;
  return { terrain: Math.max(0, 1 - s.slope_deg / 90), sunlight: Math.min(1, v.sunlight_hours / d),
    communication: Math.min(1, v.earth_visible_hours / d), navigation: r && r.accessible ? Math.max(0, 1 - r.distance_m / 100000) : 0 };
}
const PRIO = { sunlight: ["Energy (sunlight)", "var(--sun)"], communication: ["Earth communication", "var(--link)"], terrain: ["Terrain safety", "var(--ground)"], navigation: ["Traverse", "var(--route)"] };
// NASA Artemis III candidate landing regions (announced 20 Aug 2022), approximate centres as tabulated in
// Remote Sensing 17(9):1579 (2025). Each region is about 15 x 15 km. Only those inside the terrain grid are drawn.
const ARTEMIS_REGIONS = [
  { name: "Peak Near Shackleton", lat: -88.82, lon: 123.37 },
  { name: "Connecting Ridge", lat: -89.05, lon: -136.07 },
  { name: "Connecting Ridge Extension", lat: -89.0, lon: -101.4 },
];
// Readable site names built from NASA reference data: the Artemis III candidate region the site lies in
// (within 7.5 km of its centre), else the nearest IAU-named feature in the LOLA grid, with the distance.
// Shackleton's rim radius (about 10.5 km, NASA LOLA) gives "rim". The backend site_id is kept for search.
const SHACKLETON_RIM_M = 10500;
const NAMES = { plan: null, terrain: null, byId: new Map() };
function buildNames() {
  if (NAMES.plan === S.plan && NAMES.terrain === S.terrain) return;
  NAMES.plan = S.plan; NAMES.terrain = S.terrain; NAMES.byId = new Map();
  if (!S.plan) return;
  const feats = S.terrain?.features || [];
  const sites = [...new Map(S.plan.candidates.map((o) => [o.site.site_id, o.site])).values()];
  const raw = sites.map((site) => {
    if (!/^site_/.test(site.name) && site.name !== site.site_id) return [site.site_id, site.name];  // supplier already named it
    const here = { lat_deg: site.latitude_deg, lon_deg: lon180(site.longitude_deg) };
    const km = (d) => `${(d / 1000).toFixed(1)} km`;
    const art = ARTEMIS_REGIONS.map((a) => ({ a, d: haversineM(here, { lat_deg: a.lat, lon_deg: a.lon }) })).sort((x, y) => x.d - y.d)[0];
    if (isLola(S.terrain) && art && art.d <= 7500) return [site.site_id, `${art.a.name} (Artemis III region)`];
    const f = feats.map((x) => ({ x, d: haversineM(here, { lat_deg: x.lat_deg, lon_deg: x.lon_deg }) })).sort((a, b) => a.d - b.d)[0];
    if (!f) return [site.site_id, site.name];
    const base = f.x.name.replace(/ \(sunlit\)$/, "");
    if (/^Shackleton/.test(base) && Math.abs(f.d - SHACKLETON_RIM_M) <= 3000) return [site.site_id, `Shackleton rim, ${km(f.d)} from centre`];
    if (f.x.kind === "ridge" && f.d <= 2000) return [site.site_id, `On ${base}`];
    return [site.site_id, `Near ${base}, ${km(f.d)}`];
  });
  const count = new Map(); raw.forEach(([, n]) => count.set(n, (count.get(n) || 0) + 1));
  const seen = new Map();
  for (const [id, n] of raw) {
    if (count.get(n) > 1) { const k = (seen.get(n) || 0) + 1; seen.set(n, k); NAMES.byId.set(id, `${n} (${String.fromCharCode(64 + k)})`); }
    else NAMES.byId.set(id, n);
  }
}
const nm = (site) => { buildNames(); return NAMES.byId.get(site.site_id) || site.name; };
const COLORS = { recommended: "#F2C35B", feasible: "#69C6EE", rejected: "#F07A6A", p3: "#5aa9ff", dest: "#C3A6F2", sample: "#ffffff", rover: "#A9C99A", astro: "#69C6EE", hazard: "#F07A6A" };

/* ================= mission types ================= */
const TYPES = {
  science: { label: "Scientific exploration", prio: { sunlight: 2, communication: 2, terrain: 2, navigation: 1 }, nav: true, duration: 96, actors: ["rover", "astronaut"] },
  crewed: { label: "Astronaut exploration", prio: { sunlight: 1.5, communication: 3, terrain: 3, navigation: 1 }, nav: true, duration: 72, actors: ["astronaut", "rover"] },
  robotic: { label: "Rover exploration", prio: { sunlight: 2, communication: 1, terrain: 1.5, navigation: 2 }, nav: true, duration: 168, actors: ["rover"] },
  long_duration: { label: "Long-duration mission", prio: { sunlight: 3, communication: 3, terrain: 1, navigation: 0 }, nav: false, duration: 336, actors: ["rover"] },
};
const mtype = () => $('input[name=mtype]:checked').value;

/* ================= phases ================= */
function go(phase) {
  S.phase = phase; document.body.dataset.phase = phase;
  $$(".step").forEach((b) => (b.dataset.go === phase ? b.setAttribute("aria-current", "step") : b.removeAttribute("aria-current")));
  moon?.setActive(phase === "cabin" || phase === "define" || phase === "agents");
  if (phase === "explore") { mountView("slot-explore"); setViewMode(S.viewMode); refreshExplorer(); if (!go.fitted) { explorer.fitSites(); go.fitted = true; } }
  if (phase === "safety") { mountView("slot-safety"); renderSafety(); }
  if (phase !== "explore" && phase !== "safety") exitWalk(true);
  scrollTo(0, 0);
}
$$(".step").forEach((b) => b.addEventListener("click", () => !b.disabled && go(b.dataset.go)));
const unlock = (phase, on = true) => ($(`.step[data-go="${phase}"]`).disabled = !on);

/* ================= stars + moon + cabin ================= */
function stars() {
  const c = $("#stars"), d = Math.min(devicePixelRatio || 1, 2); c.width = innerWidth * d; c.height = innerHeight * d;
  const x = c.getContext("2d"); let seed = 7; const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  for (let i = 0; i < 420; i++) { const a = rnd() ** 3 * 0.8 + 0.08; x.fillStyle = `rgba(220,228,240,${a})`; x.beginPath(); x.arc(rnd() * c.width, rnd() * c.height, (rnd() * 1.1 + 0.25) * d, 0, 7); x.fill(); }
}
stars(); addEventListener("resize", stars);
let moon = null; try { moon = mountMoon($("#moon")); } catch (e) { console.warn(e); }
mountCabin($("#cabin"), { onStart: () => { go("define"); $("#launch").focus({ preventScroll: true }); } });
function led(id, state, text) { const l = $(`#led-${id}`); if (!l) return; l.className = `led ${state}`; $(`#st-${id}`).textContent = text; }

/* ================= briefing form ================= */
const form = $("#brief");
function fill(r) { const p = ((r.value - r.min) / (r.max - r.min)) * 100; r.style.setProperty("--fill", `${p}%`); }
function applyPreset(type) {
  const t = TYPES[type]; $("#p-sun").value = t.prio.sunlight; $("#p-comm").value = t.prio.communication; $("#p-terrain").value = t.prio.terrain; $("#p-nav").value = t.prio.navigation || 1;
  $("#nav-on").checked = t.nav; $("#duration").value = t.duration;
  $("#preset-note").innerHTML = `Good settings for this mission type are already applied (${t.duration} h stay). Change them in <b>Advanced settings</b> below if you need to.`;
  syncForm();
}
function syncForm() {
  $$("input[type=range]", form).forEach(fill);
  $$(".prio", form).forEach((p) => ($("output", p).textContent = $("input", p).value));
  const set = (id, v) => ($(id).textContent = v);
  set("#dur-out", `${$("#duration").value} h`); set("#slope-out", `${$("#max-slope").value}°`); set("#minsun-out", `${$("#min-sun").value} h`);
  set("#blackout-out", `${$("#max-blackout").value} h`); set("#maxroute-out", fmtM(+$("#max-route").value)); set("#days-out", $("#days").value);
  set("#a-slope-out", `${$("#a-slope").value}°`); set("#a-km-out", `${$("#a-km").value} km`); set("#a-h-out", `${$("#a-h").value} h`);
  set("#r-slope-out", `${$("#r-slope").value}°`); set("#r-speed-out", `${(+$("#r-speed").value).toFixed(2)} m/s`); set("#r-batt-out", `${$("#r-batt").value} Wh`);
  Object.assign(S.assumptions.astronaut, { max_slope_deg: +$("#a-slope").value, max_eva_km: +$("#a-km").value, max_eva_h: +$("#a-h").value });
  Object.assign(S.assumptions.rover, { max_slope_deg: +$("#r-slope").value, speed_mps: +$("#r-speed").value, battery_wh: +$("#r-batt").value });
  const nav = $("#nav-on").checked; $("#nav-opts").hidden = !nav;
  const w = { sun: +$("#p-sun").value, comm: +$("#p-comm").value, terrain: +$("#p-terrain").value, nav: nav ? +$("#p-nav").value : 0 };
  for (const k in w) $(`#bal-${k}`).style.flexGrow = w[k];
  const d = +$("#days").value, r = buildRequirements();
  $("#brief-summary").innerHTML = `<b>${esc(TYPES[mtype()].label)}</b>: lands ${esc(utc(r.dates_utc[0]))}, stays <b>${r.duration_hours} h</b>${d > 1 ? `, and also checks the next ${d - 1} day${d > 2 ? "s" : ""}` : ""}.`;
}
$$("[data-step]", form).forEach((b) => b.addEventListener("click", () => { const el = $("#days"); el.value = Math.max(1, Math.min(10, +el.value + +b.dataset.step)); syncForm(); }));
form.addEventListener("input", syncForm);
$$('input[name=mtype]').forEach((r) => r.addEventListener("change", () => r.checked && applyPreset(r.value)));
$("#dest-select").addEventListener("change", (e) => { S.customStops.destination = e.target.value === "auto" ? null : JSON.parse(e.target.value); S.sim = null; });

function buildRequirements() {
  const date = $("#date").value || "2030-01-01", time = ($("#time").value || "00:00").slice(0, 5);
  const days = +$("#days").value, base = new Date(`${date}T${time}:00Z`);
  const dates = Array.from({ length: days }, (_, i) => new Date(base.getTime() + i * 86400000).toISOString().replace(".000Z", "Z"));
  const nav = $("#nav-on").checked, type = mtype();
  const constraints = { max_slope_deg: +$("#max-slope").value, min_sunlight_hours: +$("#min-sun").value, max_blackout_hours: +$("#max-blackout").value };
  if (nav) constraints.max_route_m = +$("#max-route").value;
  const objectives = [];
  if (+$("#p-sun").value > 0) objectives.push("energy"); if (+$("#p-comm").value > 0) objectives.push("Earth communication");
  if (+$("#p-terrain").value > 0) objectives.push("terrain safety"); if (nav) objectives.push("traverse");
  // The supervisor re-reads mission type from this text when mission_type is "science", so name the type itself.
  return { request: `${type.replace("_", "-")} mission near lunar south pole`, mission_type: type, dates_utc: dates, duration_hours: +$("#duration").value, objectives,
    priorities: { terrain: +$("#p-terrain").value, sunlight: +$("#p-sun").value, communication: +$("#p-comm").value, navigation: nav ? +$("#p-nav").value : 0 },
    constraints, require_navigation: nav, allow_mock_recommendation: $("#allow-mock").checked };
}
function clientCheck(r) {
  if (Object.values(r.priorities).reduce((a, b) => a + b, 0) <= 0) return "Give at least one priority a weight above zero.";
  if (!(r.duration_hours > 0)) return "Surface stay must be longer than zero hours.";
  if (Number.isNaN(new Date(r.dates_utc[0]).getTime())) return "Pick a valid landing day and time.";
  return null;
}
form.addEventListener("submit", (e) => { e.preventDefault(); launch(); });
$("#new-mission").addEventListener("click", () => { S.replanMode = false; setReplanUi(); toast("Next launch starts a new mission ID."); });
function setReplanUi() {
  const on = S.replanMode && S.plan; $("#launch").textContent = on ? "Replan mission" : "Launch mission analysis";
  $("#new-mission").hidden = !on; const chip = $("#mission-id-chip"); chip.hidden = !on; if (on) chip.textContent = `Replanning ${S.plan.mission_id.slice(0, 8)}`;
}

/* ================= pipeline (Mission 02) ================= */
const NODES = [
  { id: "supervisor", name: "Mission supervisor", role: "Reads the request and settles the mission type. Calls an LLM only if the server has an API key." },
  { id: "site_analysis", name: "Landing site analysis", role: "Fetches candidate sites with slope and elevation from the site service." },
  { id: "visibility_analysis", name: "Sunlight and Earth visibility", role: "Measures sunlight, Earth-visible hours and the longest blackout for every site and day." },
  { id: "navigation_analysis", name: "Conditional navigation", role: "Plans a traverse for each option. Runs only when traverse access is part of the ranking.", branch: true },
  { id: "validation", name: "Scientific validation", role: "Checks every option against your landing rules and the provenance of its data." },
  { id: "optimization", name: "Mission optimization", role: "Scores feasible options, then ranks them through Pareto layers and a MILP selection." },
  { id: "explanation", name: "Explanation", role: "Writes an evidence-based reason for every accepted and rejected option." },
];
function renderPipeline(states = {}, evidence = {}) {
  $("#pipeline").innerHTML = NODES.map((n, i) => {
    const s = states[n.id] || "idle";
    const pill = { idle: "Standing by", waiting: "Awaiting response", done: "Ran, confirmed by response", skipped: "Skipped by graph", halted: "Not confirmed" }[s];
    const ev = evidence[n.id];
    return `<li class="agent${n.branch ? " branch" : ""}" data-s="${s}"><div class="node">${String(i + 1).padStart(2, "0")}</div>
      <div class="card"><div class="row1"><h3>${n.name}</h3><span class="pill">${pill}</span></div><p class="role">${n.role}</p>
      ${ev ? `<div class="evidence">${ev.map(([k, v]) => `<div><span>${esc(k)}</span><span>${v}</span></div>`).join("")}</div>` : ""}</div></li>`;
  }).join("");
}
function evidenceFrom(resp) {
  const req = resp.requirements, c = resp.candidates, m = resp.metrics || {};
  const sites = [...new Map(c.map((o) => [o.site.site_id, o.site])).values()];
  const statuses = (list) => [...new Set(list)].map(badge).join(" ");
  const feasible = c.filter((o) => o.feasible), rejected = c.filter((o) => !o.feasible);
  const vcount = {}; rejected.forEach((o) => o.violations.forEach((v) => (vcount[v] = (vcount[v] || 0) + 1)));
  const topV = Object.entries(vcount).sort((a, b) => b[1] - a[1])[0]; const routes = c.filter((o) => o.route);
  const e = {
    supervisor: [["Mission type", esc(req.mission_type)], ["LLM calls", m.llm_calls ? `${m.llm_calls} (${esc(resp.llm_provider || "llm")})` : "0, deterministic interpretation"]],
    site_analysis: [["Sites returned", `${sites.length}`], ["Source", esc([...new Set(sites.map((s) => s.provenance.source))].join("; "))], ["Data status", statuses(sites.map((s) => s.provenance.status))]],
    visibility_analysis: [["Measurements", `${c.length} (${sites.length} sites × ${req.dates_utc.length} days)`], ["Data status", statuses(c.map((o) => o.visibility.provenance.status))]],
    validation: [["Feasible", `${feasible.length} of ${c.length}`], ["Most common rejection", topV ? `${esc(topV[0])} (${topV[1]})` : "none"]],
    optimization: [["Ranked alternatives", `${resp.ranked_alternatives.length}`], ["Method", "Pareto layers, MILP selection"], ["Top score", resp.recommendation ? resp.recommendation.score.toFixed(4) : "no feasible option"]],
    explanation: [["Explanations written", `${c.filter((o) => o.explanation).length}`], ["Recommendation", resp.recommendation ? esc(`${nm(resp.recommendation.site)}, ${day(resp.recommendation.visibility.date_utc)}`) : "none"]],
  };
  e.navigation_analysis = req.require_navigation ? [["Routes returned", `${routes.length}`], ["Accessible", `${routes.filter((r) => r.route.accessible).length}`], ["Data status", statuses(routes.map((o) => o.route.provenance.status))]]
    : [["Why skipped", "Traverse access was not part of the ranking, so the graph went straight to validation"]];
  return e;
}
let timer = 0;
function reqStatus(state, text, running) { $("#req-status").innerHTML = `<span class="state">${state}</span><span>${text}</span><span class="bar${running ? " run" : ""}"></span>`; }
async function launch() {
  if (S.busy) return;
  const req = buildRequirements(), bad = clientCheck(req), errEl = $("#brief-error");
  if (bad) { errEl.textContent = bad; errEl.hidden = false; return; }
  errEl.hidden = true; S.busy = true; $("#launch").disabled = true;
  const replan = S.replanMode && S.plan, path = replan ? "/mission/replan" : "/mission/plan";
  unlock("agents"); go("agents");
  renderPipeline(Object.fromEntries(NODES.map((n) => [n.id, "waiting"])));
  $("#cc-foot").innerHTML = `<p>The planner runs every step inside one request and reports once at the end. It does not stream progress, so a step turns green only when the response shows it ran.</p>`;
  const t0 = performance.now(); const tick = () => reqStatus("Request in flight", `POST ${path}, ${((performance.now() - t0) / 1000).toFixed(1)} s elapsed`, true);
  tick(); clearInterval(timer); timer = setInterval(tick, 100);
  try {
    const resp = replan ? await planner.replan(S.plan, req) : await planner.plan(req);
    clearInterval(timer);
    reqStatus(CONFIG.recorded ? "Recorded NASA-data run" : "Response received", CONFIG.recorded ? `Replayed from the live backend on NASA data (LOLA + JPL Horizons), recorded ${esc(recordedAt)}. Backend runtime then: ${resp.metrics?.runtime_ms ?? "?"} ms, mission ${esc(resp.mission_id.slice(0, 8))}.` : `HTTP 200 in ${((performance.now() - t0) / 1000).toFixed(2)} s. Backend runtime ${resp.metrics?.runtime_ms ?? "?"} ms, mission ${esc(resp.mission_id.slice(0, 8))}${replan ? " (same ID, replanned)" : ""}`, false);
    const states = Object.fromEntries(NODES.map((n) => [n.id, "done"])); if (!resp.requirements.require_navigation) states.navigation_analysis = "skipped";
    renderPipeline(states, evidenceFrom(resp));
    const c = resp.candidates, nSites = new Set(c.map((o) => o.site.site_id)).size, expected = 1 + c.length + (resp.requirements.require_navigation ? c.length : 0), tc = resp.metrics?.tool_calls;
    $("#cc-foot").innerHTML = `<p>Tool calls reported by the backend: <b>${tc}</b>${tc === expected ? `, matching 1 site query, ${c.length} visibility analyses${resp.requirements.require_navigation ? ` and ${c.length} route queries` : ""}` : tc < expected ? `. Fewer than ${expected} because verified measurements were reused` : ""}. ${nSites} sites over ${resp.requirements.dates_utc.length} days.</p>
      <button class="btn primary" id="to-map">Explore candidate sites in 3D</button><button class="btn" id="to-dossier">${resp.recommendation ? "Open landing site" : "See why nothing qualified"}</button>`;
    $("#to-dossier").onclick = () => go("discover"); $("#to-map").onclick = () => go("explore");
    S.plan = resp; S.lastReq = req; S.compare = null; S.replanMode = false; S.sim = null; setReplanUi();
    const rec = resp.recommendation || resp.candidates[0]; S.sel = rec ? { siteId: rec.site.site_id, date: rec.visibility.date_utc } : null;
    unlock("discover"); unlock("safety", !!resp.recommendation); go.fitted = false;
    if (resp.recommendation) runSim(); renderDossier(); loadPlanIntoMap(); setService("planner", true, CONFIG.recorded ? "recorded NASA runs" : undefined);
  } catch (err) {
    clearInterval(timer);
    const e = err instanceof ApiError ? err : new ApiError("http", 0, String(err));
    reqStatus({ validation: "Request rejected (422)", upstream: "Planner failed (502)", network: "Planner unreachable", recorded: "Needs the live planner", http: `HTTP ${e.status}` }[e.kind], esc(e.message), false);
    renderPipeline(Object.fromEntries(NODES.map((n) => [n.id, "halted"])));
    $("#cc-foot").innerHTML = `<p>${e.kind === "upstream" ? "The backend reports a failure for the whole request and does not say which step failed, so no step is marked as completed." : e.kind === "validation" ? "The backend refused the requirements before any step ran. Adjust the briefing and launch again." : e.kind === "recorded" ? "On this public site, choose one of the four mission types and keep its default settings to see the recorded NASA-data run." : "No request reached the planning graph."}</p>
      <button class="btn primary" id="back-brief">Back to briefing</button><button class="btn" id="retry">Retry launch</button>`;
    $("#back-brief").onclick = () => go("define"); $("#retry").onclick = () => launch();
    if (e.kind === "network") setService("planner", false);
  } finally { S.busy = false; $("#launch").disabled = false; }
}

/* ================= dossier (Mission 04) ================= */
const SUGGEST = {
  "slope exceeds maximum": "Raise the steepest landing slope in Landing rules.", "insufficient sunlight": "Lower the minimum sunlight, or shorten the stay.",
  "blackout exceeds maximum": "Allow a longer Earth blackout in Landing rules.",
  "mock data disallowed": "The backend is running on mock fixtures. Allow a provisional recommendation from mock data, or connect real site and visibility services.",
  "unverified scientific data": "Supplier data marked REAL is held as unverified until independent review. The planner will not recommend from it.",
  "route exceeds maximum distance": "Allow a longer traverse.", "route inaccessible": "The traverse is blocked by terrain. Try without traverse access in the ranking.",
  "visibility duration exceeds mission duration": "The visibility service returned more hours than the stay; check the service configuration.", "route missing": "The navigation service returned no route.",
};
function gauge(label, color, value, max, valText, cap, marker) {
  const w = Math.max(0, Math.min(1, value / max)) * 100; const mk = marker != null ? `<b style="left:${Math.min(100, (marker / max) * 100)}%" title="Your limit"></b>` : "";
  return `<div class="gauge" style="--c:${color}"><div class="top2"><span>${label}</span><span class="val">${valText}</span></div><div class="track"><i style="width:${w}%"></i>${mk}</div><div class="cap">${cap}</div></div>`;
}
function ring(score) { const r = 38, c = 2 * Math.PI * r;
  return `<svg class="ring" viewBox="0 0 92 92" aria-hidden="true"><circle cx="46" cy="46" r="${r}" fill="none" stroke="var(--line)" stroke-width="8"/><circle cx="46" cy="46" r="${r}" fill="none" stroke="var(--sun)" stroke-width="8" stroke-linecap="round" stroke-dasharray="${c * score} ${c}" transform="rotate(-90 46 46)"/></svg>`; }
/** Sunlight / Earth-visibility timeline across the candidate days for one site (values straight from the plan). */
function daysChart(P, siteId, chosenDate) {
  const opts = P.candidates.filter((o) => o.site.site_id === siteId).sort((a, b) => a.visibility.date_utc.localeCompare(b.visibility.date_utc));
  const d = P.requirements.duration_hours, W = 520, H = 150, pad = 28, bw = Math.min(60, (W - pad * 2) / opts.length / 2.4);
  const y = (h) => H - 24 - (h / d) * (H - 44);
  const bars = opts.map((o, i) => { const cx = pad + ((i + 0.5) / opts.length) * (W - pad * 2), v = o.visibility, on = v.date_utc === chosenDate;
    return `<rect x="${cx - bw - 2}" y="${y(v.sunlight_hours)}" width="${bw}" height="${H - 24 - y(v.sunlight_hours)}" rx="3" fill="var(--sun)" opacity="${on ? 1 : 0.55}"><title>Sunlight ${v.sunlight_hours.toFixed(1)} h</title></rect>
      <rect x="${cx + 2}" y="${y(v.earth_visible_hours)}" width="${bw}" height="${H - 24 - y(v.earth_visible_hours)}" rx="3" fill="var(--link)" opacity="${on ? 1 : 0.55}"><title>Earth visible ${v.earth_visible_hours.toFixed(1)} h</title></rect>
      <text x="${cx}" y="${H - 8}" text-anchor="middle" fill="${on ? "var(--regolith)" : "var(--dust)"}" font-size="11">${esc(day(v.date_utc))}${o.feasible ? "" : " ✕"}</text>`; }).join("");
  return `<svg class="days-chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Sunlight and Earth-visible hours per candidate landing day">
    <line x1="${pad}" x2="${W - pad}" y1="${y(d)}" y2="${y(d)}" stroke="var(--line)" stroke-dasharray="4 4"/><text x="${pad}" y="${y(d) - 4}" fill="var(--dust)" font-size="10.5">${d} h stay</text>${bars}</svg>
    <div class="contrib-keys"><span><i style="background:var(--sun)"></i>Sunlight hours</span><span><i style="background:var(--link)"></i>Earth-visible hours</span><span>Totals per landing day from the visibility service. Hour-by-hour timing is not provided.</span></div>`;
}
function renderDossier() {
  const P = S.plan, el = $("#dossier"); if (!P) return;
  const req = P.requirements, rec = P.recommendation, warn = [...P.warnings, ...P.limitations];
  const warnHtml = warn.length ? `<div class="provisional"><b>Read before using these results</b><ul>${warn.map((w) => `<li>${esc(w)}</li>`).join("")}</ul></div>` : "";
  if (!rec) {
    const counts = {}; P.candidates.forEach((o) => o.violations.forEach((v) => (counts[v] = (counts[v] || 0) + 1))); const sorted = Object.entries(counts).sort((a, b) => b[1] - a[1]);
    el.innerHTML = `<div class="empty"><p class="kicker">Mission 04</p><h1>No site meets every landing rule</h1><p>The planner checked ${P.candidates.length} site and day combinations and rejected all of them. Here is what blocked them.</p></div>${warnHtml}
      <div class="panel"><h2>Rejection reasons</h2><ul class="rej">${sorted.map(([v, n]) => `<li><span class="v">${esc(v)}</span>, ${n} of ${P.candidates.length} options. ${esc(SUGGEST[v] || "")}</li>`).join("") || "<li>The site service returned no candidates.</li>"}</ul>
      <div class="d-actions" style="justify-content:flex-start;margin-top:12px"><button class="btn primary" data-act="replan">Adjust rules and replan</button><button class="btn" data-act="map">Inspect sites in 3D</button></div></div>`;
    bindDossier(); return;
  }
  const s = rec.site, v = rec.visibility, d = req.duration_hours, end = new Date(new Date(v.date_utc).getTime() + d * 3600e3).toISOString();
  const u = utilities(rec, req), W = Object.values(req.priorities).reduce((a, b) => a + b, 0);
  const parts = Object.keys(PRIO).filter((k) => req.priorities[k] > 0).map((k) => [k, (req.priorities[k] * u[k]) / W]);
  const recomputed = parts.reduce((a, [, x]) => a + x, 0), strongest = [...parts].sort((a, b) => b[1] - a[1])[0], others = P.ranked_alternatives.slice(1);
  const mock = [s.provenance, v.provenance, rec.route?.provenance].some((p) => p && p.status !== "VERIFIED"); const rejected = P.candidates.filter((o) => !o.feasible);
  // trade-offs vs runner-up, purely from returned numbers
  const tradeoffs = others.length ? (() => { const b = others[0], out = [];
    const cmp = (label, a, c, unit, better) => { const diff = a - c; if (Math.abs(diff) < 0.05) return; out.push(`${(better === "high" ? diff > 0 : diff < 0) ? "better" : "worse"} ${label} (${a.toFixed(1)} vs ${c.toFixed(1)} ${unit})`); };
    cmp("sunlight", v.sunlight_hours, b.visibility.sunlight_hours, "h", "high"); cmp("Earth visibility", v.earth_visible_hours, b.visibility.earth_visible_hours, "h", "high");
    cmp("slope", s.slope_deg, b.site.slope_deg, "°", "low"); cmp("longest blackout", v.max_blackout_hours, b.visibility.max_blackout_hours, "h", "low");
    return out.length ? `Against ${esc(nm(b.site))} on ${esc(day(b.visibility.date_utc))}: ${out.join(", ")}.` : ""; })() : "";
  const sim = S.sim && !S.sim.error ? S.sim : null;
  el.innerHTML = `
    <div class="d-head"><div><p class="kicker">Mission 04, recommended landing site</p><h1>${esc(nm(s))}</h1>
      <p class="coords">Site ${esc(s.site_id)}, ${latS(s.latitude_deg)}, ${lonE(s.longitude_deg)}, elevation ${Math.round(s.elevation_m)} m ${badge(s.provenance.status)}</p>
      ${(() => { const here = { lat_deg: s.latitude_deg, lon_deg: lon180(s.longitude_deg) };
        const near = ARTEMIS_REGIONS.map((a) => ({ a, d: haversineM(here, { lat_deg: a.lat, lon_deg: a.lon }) })).sort((x, y) => x.d - y.d)[0];
        return near && near.d < 20000 ? `<p class="coords" style="color:var(--sun)">${(near.d / 1000).toFixed(1)} km from the centre of NASA's Artemis III candidate region "${esc(near.a.name)}" (regions are about 15 × 15 km)${near.d <= 7500 ? ", inside it" : ""}.</p>` : ""; })()}</div>
      <div class="d-actions"><button class="btn" data-act="map">Show in 3D</button><button class="btn" data-act="walk">LUNA WALK the site</button><button class="btn" data-act="replan">Adjust and replan</button><button class="btn" data-act="compare">Compare with baseline</button></div></div>
    ${warnHtml}
    <div class="d-grid">
      <div class="panel"><h2>Landing window</h2>
        <p class="window-line">${esc(utc(v.date_utc))} to ${esc(utc(end))}</p>
        <p class="cap" style="color:var(--dust);margin:0">${d} h on the surface. Visibility ${badge(v.provenance.status)}</p>
        ${gauge("Solar illumination", "var(--sun)", v.sunlight_hours, d, `${h1(v.sunlight_hours)} <small>of ${d} h</small>`, `${pct(Math.min(1, v.sunlight_hours / d))} of the stay in sunlight. Your minimum: ${req.constraints.min_sunlight_hours ?? 0} h.`, req.constraints.min_sunlight_hours)}
        ${gauge("Earth communication", "var(--link)", v.earth_visible_hours, d, `${h1(v.earth_visible_hours)} <small>of ${d} h</small>`, `${pct(Math.min(1, v.earth_visible_hours / d))} of the stay with Earth in view.`)}
        ${gauge("Longest Earth blackout", "var(--halt)", v.max_blackout_hours, Math.max(req.constraints.max_blackout_hours ?? 72, v.max_blackout_hours) || 1, h1(v.max_blackout_hours), `Your limit: ${req.constraints.max_blackout_hours ?? "none"} h.`, req.constraints.max_blackout_hours)}
        ${gauge("Terrain slope", "var(--ground)", s.slope_deg, 30, `${s.slope_deg.toFixed(1)}°`, `Your limit: ${req.constraints.max_slope_deg ?? 90}°.`, req.constraints.max_slope_deg)}
        ${rec.route ? gauge("Planner traverse", "var(--route)", rec.route.distance_m, Math.max(req.constraints.max_route_m ?? 100000, rec.route.distance_m), fmtM(rec.route.distance_m), `${rec.route.accessible ? "Accessible" : "Blocked"}. ${badge(rec.route.provenance.status)}`, req.constraints.max_route_m) : ""}
      </div>
      <div style="display:grid;gap:18px;align-content:start">
        <div class="panel"><h2>Mission suitability</h2><div class="feas">${ring(rec.score)}<div><div class="big">${rec.score.toFixed(3)}</div>
          <div>Weighted score, passes every landing rule${mock ? ", provisional" : ""}</div>
          <div class="cap" style="color:var(--dust);font-size:12.5px">Ranked first of ${P.ranked_alternatives.length} feasible options out of ${P.candidates.length} checked.</div></div></div></div>
        <div class="panel safety-card"><h2>Safety and continuity</h2>${sim ? `<div class="verdict ${sim.overall}" style="margin:0 0 10px"><b>${VERDICT[sim.overall].t}</b><p>${VERDICT[sim.overall].p}</p></div>
          <div class="nums"><div><b>${sim.totals.km ? sim.totals.km.toFixed(1) : "–"} km</b>Rover loop</div><div><b>${Number.isFinite(sim.totals.total_h) ? sim.totals.total_h.toFixed(1) : "–"} h</b>Operations time</div><div><b>${sim.hazards.filter((h) => h.severity !== "info").length}</b>Hazards flagged</div></div>`
          : `<p style="color:var(--dust);font-size:13.5px">${S.sim?.error ? esc(S.sim.error) : S.terrain ? "Not run yet." : "Loading terrain…"}</p>`}
          <button class="btn primary" data-act="safety" style="margin-top:12px">Open safety simulation</button></div>
        <div class="panel why"><h2>Why was this site selected?</h2>
          <p>${strongest ? `Its largest contribution comes from ${PRIO[strongest[0]][0].toLowerCase()}, which you weighted ${req.priorities[strongest[0]]}.` : ""} ${others.length ? `It beats the runner-up by ${(rec.score - others[0].score).toFixed(3)}.` : "It is the only feasible option."} ${tradeoffs}</p>
          <div class="contrib">${parts.map(([k, x]) => `<span style="width:${x * 100}%;background:${PRIO[k][1]}" title="${PRIO[k][0]} ${x.toFixed(3)}"></span>`).join("")}</div>
          <div class="contrib-keys">${parts.map(([k, x]) => `<span><i style="background:${PRIO[k][1]}"></i>${PRIO[k][0]} ${x.toFixed(3)}</span>`).join("")}</div>
          <p class="check">Breakdown recomputed in the browser from the documented scoring formula: ${recomputed.toFixed(4)}${Math.abs(recomputed - rec.score) < 1e-4 ? ", matching the backend score" : `, backend reports ${rec.score.toFixed(4)}`}.</p>
          <p style="margin-top:10px"><b>Planner explanation:</b> ${esc(rec.explanation)}</p>
          ${P.ai_summary ? `<p class="ai-sum"><b>AI summary</b> <span class="ai-tag" title="Written by Gemini from the agents' numbers only. Every number was checked against the evidence; any unmatched number would have rejected the text.">Gemini · numbers checked</span><br>${esc(P.ai_summary)}</p>` : ""}
          ${sim ? `<p style="margin-top:8px"><b>Remaining risks:</b> ${sim.hazards.filter((h) => h.severity !== "info").map((h) => esc(h.title)).join("; ") || "none flagged by the safety simulation under current assumptions"}.</p>` : ""}</div>
      </div>
      <div class="panel span2"><h2>Sunlight and Earth visibility by landing day</h2>${daysChart(P, s.site_id, v.date_utc)}</div>
      <div class="panel span2"><h2>Alternative landing options</h2>
        <table class="alts"><thead><tr><th>Rank</th><th>Site</th><th>Day</th><th>Sunlight</th><th>Earth in view</th><th>Blackout</th><th>Slope</th><th>Score</th></tr></thead><tbody>
        ${P.ranked_alternatives.map((o, i) => `<tr class="${i === 0 ? "top" : ""}" data-site="${esc(o.site.site_id)}" data-date="${esc(o.visibility.date_utc)}" tabindex="0" title="Show in 3D">
          <td>${i + 1}</td><td>${esc(nm(o.site))} <span class="sid">${esc(o.site.site_id)}</span></td><td>${esc(day(o.visibility.date_utc))}</td>
          <td>${h1(o.visibility.sunlight_hours)}</td><td>${h1(o.visibility.earth_visible_hours)}</td><td>${h1(o.visibility.max_blackout_hours)}</td><td>${o.site.slope_deg.toFixed(1)}°</td>
          <td><span class="sbar"><i style="width:${o.score * 100}%"></i></span>${o.score.toFixed(3)}</td></tr>`).join("")}</tbody></table>
        ${rejected.length ? `<h2 style="margin-top:18px;font-size:17px">Rejected (${rejected.length})</h2><ul class="rej">${rejected.map((o) => `<li>${esc(nm(o.site))}, ${esc(day(o.visibility.date_utc))}: <span class="v">${esc(o.violations.join(", "))}</span></li>`).join("")}</ul>` : ""}</div>
      <div class="panel span2" id="compare-panel" ${S.compare ? "" : "hidden"}></div>
      <div class="panel span2"><h2>Run record and data provenance</h2><div class="metrics">
        <span><b>${esc(P.mission_id.slice(0, 8))}</b>Mission ID</span>${Object.entries(P.metrics || {}).map(([k, x]) => `<span><b>${esc(x)}</b>${esc(k.replace(/_/g, " "))}</span>`).join("")}
        <span><b>${esc(new Date(P.generated_at_utc).toISOString().slice(11, 19))}</b>Generated, UTC</span></div>
        <p class="prov">Site: ${esc(s.provenance.source)} ${badge(s.provenance.status)}. Visibility: ${esc(v.provenance.source)} ${badge(v.provenance.status)}${v.provenance.uncertainty ? `, ${esc(v.provenance.uncertainty)}` : ""}. Terrain for safety analysis: ${esc(S.terrain?.source?.name || "not loaded")} ${S.terrain ? tBadge(S.terrain) : ""}, ${S.terrain ? `${S.terrain.cell} m grid, ${tOrigin(S.terrain)}` : ""}. Frame IAU_MOON_2015, east-positive longitude.</p></div>
    </div>`;
  bindDossier(); if (S.compare) renderCompare();
}
function bindDossier() {
  $$("[data-act]", $("#dossier")).forEach((b) => b.addEventListener("click", () => {
    const a = b.dataset.act, o = S.plan.recommendation;
    if (a === "map") { go("explore"); if (o) selectSite(o.site.site_id, o.visibility.date_utc, true); }
    if (a === "walk" && o) { go("explore"); setViewMode("3d"); selectSite(o.site.site_id, o.visibility.date_utc); enterWalk({ lat: o.site.latitude_deg, lon: o.site.longitude_deg, name: nm(o.site) }); }
    if (a === "replan") { S.replanMode = true; setReplanUi(); go("define"); $("#launch").focus(); }
    if (a === "compare") runCompare(b);
    if (a === "safety") go("safety");
  }));
  $$(".alts tr[data-site]").forEach((tr) => { const open = () => { go("explore"); selectSite(tr.dataset.site, tr.dataset.date, true); };
    tr.addEventListener("click", open); tr.addEventListener("keydown", (e) => e.key === "Enter" && open()); });
}
async function runCompare(btn) {
  btn.disabled = true; btn.textContent = "Comparing…"; const panel = $("#compare-panel"); panel.hidden = false;
  panel.innerHTML = `<h2>Baseline and hybrid ranking</h2><p style="color:var(--dust)">POST /mission/compare in flight. The backend runs the full graph twice.</p>`;
  try { S.compare = await planner.compare(S.plan.requirements); renderCompare(); }
  catch (e) { panel.innerHTML = `<h2>Baseline and hybrid ranking</h2><p class="err">${esc(e.message)}</p>`; }
  finally { btn.disabled = false; btn.textContent = "Compare with baseline"; }
}
function renderCompare() {
  const C = S.compare, panel = $("#compare-panel"); if (!C || !panel) return; panel.hidden = false;
  const col = (title, r, m) => `<div><h3>${title}</h3><ol>${r.ranked_alternatives.slice(0, 6).map((o) => `<li>${esc(nm(o.site))}, ${esc(day(o.visibility.date_utc))}: ${o.score.toFixed(3)}</li>`).join("") || "<li>No feasible option</li>"}</ol><p class="check">Runtime ${esc(m.runtime_ms)} ms, ${esc(m.tool_calls)} tool calls</p></div>`;
  const same = C.baseline.recommendation && C.hybrid.recommendation && optKey(C.baseline.recommendation) === optKey(C.hybrid.recommendation);
  panel.innerHTML = `<h2>Baseline and hybrid ranking</h2><p>${same ? "Both methods pick the same site and day." : "The two methods pick different options."} Runtimes are single-run observations, not evidence that one method is better.</p>
    <div class="cmp">${col("Baseline: weighted score sort", C.baseline, C.metrics.baseline)}${col("Hybrid: Pareto layers with MILP", C.hybrid, C.metrics.hybrid)}</div>`;
}

/* ================= 3D view (shared) ================= */
let view = null;
try {
  view = new TerrainView($("#gl"), $("#glabels"), { onPick: (ll) => onGroundPick(ll), onModeChange: () => {} });
  view.cb.onWalk = (ll) => walkHud(ll);
} catch (e) { console.warn(e); $("#nogl").hidden = false; S.viewMode = "2d"; }
function mountView(slotId) { const slot = $(`#${slotId}`); if (slot && $("#view3d").parentElement !== slot) slot.appendChild($("#view3d")); view?.resize(); }

/* ================= Moon explorer (Mission 03) ================= */
const explorer = new MoonExplorer($("#map"), {
  onSelect: (s) => (s.layer === "plan" ? selectSite(s.id) : onGroundPick({ lat_deg: s.lat, lon_deg: s.lon }, s)),
  onPick: (ll) => onGroundPick(ll),
  onCursor: (ll) => S.viewMode === "2d" && ($("#hud").textContent = `lat ${ll.lat_deg.toFixed(4)}°, lon ${ll.lon_deg.toFixed(4)}° (east positive)`),
});
explorer.layers.p3Sites = true;
function setViewMode(m) {
  if (m === "3d" && !view) m = "2d"; S.viewMode = m;
  $$("#view-mode button").forEach((b) => b.classList.toggle("on", b.dataset.v === m));
  $("#slot-explore").hidden = m !== "3d"; $("#map").hidden = m !== "2d"; $("#tools-2d").hidden = m !== "2d"; $("#exag-wrap").hidden = m !== "3d";
  $("#hud").textContent = m === "3d" ? "Drag to rotate, right-drag or Shift-drag to pan, scroll to zoom. Click the ground to inspect it." : "South polar stereographic chart, wider than the terrain grid.";
  if (m === "2d") explorer.resize(); else view?.resize(); legend();
}
$$("#view-mode button").forEach((b) => b.addEventListener("click", () => setViewMode(b.dataset.v)));
$("#zoom-in").onclick = () => explorer.zoom(1 / 1.4); $("#zoom-out").onclick = () => explorer.zoom(1.4); $("#zoom-fit").onclick = () => explorer.fitSites();
$$("#terrain-mode button").forEach((b) => b.addEventListener("click", () => {
  $$("#terrain-mode button").forEach((x) => x.classList.toggle("on", x === b)); const m = b.dataset.mode;
  view?.setColorMode(m, S.plan?.requirements.constraints.max_slope_deg ?? 15); explorer.setTerrainMode(m === "regolith" ? "none" : m); legend(); }));
$("#exag").addEventListener("input", (e) => { $("#exag-out").textContent = `×${e.target.value}`; view?.setExaggeration(+e.target.value); });
$("#p3-sites").addEventListener("change", (e) => { explorer.layers.p3Sites = e.target.checked; explorer.render(); refreshExplorer(); });
$("#features").addEventListener("change", () => refreshExplorer());
$("#artemis").addEventListener("change", () => { refreshExplorer(); legend(); });
$("#search").addEventListener("submit", (e) => { e.preventDefault(); search($("#search-q").value.trim()); });

function search(q) {
  const msg = $("#search-msg"); msg.textContent = ""; if (!q) return;
  const m = q.match(/^(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)$/);
  if (m) { const lat = +m[1], lon = +m[2]; if (lat < -90 || lat > 90) { msg.textContent = "Latitude must be between -90 and 90."; return; } focus(lat, lon); onGroundPick({ lat_deg: lat, lon_deg: lon }); return; }
  const ql = q.toLowerCase();
  const plan = S.plan ? [...new Map(S.plan.candidates.map((o) => [o.site.site_id, o.site])).values()].find((s) => nm(s).toLowerCase().includes(ql) || s.site_id.toLowerCase().includes(ql)) : null;
  if (plan) { selectSite(plan.site_id, null, true); return; }
  const art = isLola(S.terrain) ? ARTEMIS_REGIONS.find((a) => a.name.toLowerCase().includes(ql)) : null;
  if (art) { focus(art.lat, art.lon); onGroundPick({ lat_deg: art.lat, lon_deg: art.lon }, { id: `NASA Artemis III region: ${art.name}`, layer: "feature" }); return; }
  const feat = (S.terrain?.features || []).find((f) => f.name.toLowerCase().includes(ql));
  if (feat) { focus(feat.lat_deg, feat.lon_deg); onGroundPick({ lat_deg: feat.lat_deg, lon_deg: feat.lon_deg }, { id: feat.name, layer: "feature" }); return; }
  const p3 = S.p3Sites.find((s) => s.name.toLowerCase().includes(ql) || s.site_id.toLowerCase().includes(ql));
  if (p3) { focus(p3.location.lat_deg, p3.location.lon_deg); onGroundPick({ lat_deg: p3.location.lat_deg, lon_deg: p3.location.lon_deg }, { id: p3.site_id, layer: "p3" }); return; }
  msg.textContent = "No match. Try a site name, an ID such as A or MOCK-SP-02, or coordinates like -89.1, 45.";
}
function focus(lat, lon) { if (S.viewMode === "3d") view?.flyTo(lat, lon, 26000); else explorer.flyTo(lat, lon, 90); }

function legend() {
  const mode = $("#terrain-mode .on")?.dataset.mode || "regolith";
  $("#legend").innerHTML = `${S.plan ? `<div class="k"><span class="dot" style="background:${COLORS.recommended}"></span>Recommended site</div><div class="k"><span class="dot" style="background:${COLORS.feasible}"></span>Feasible site</div><div class="k"><span class="dot" style="border:2px solid ${COLORS.rejected}"></span>Rejected on every day</div>` : ""}
    ${$("#artemis").checked && isLola(S.terrain) ? `<div class="k"><span class="dot" style="border:2px solid #F2C35B;border-radius:2px"></span>NASA Artemis III region, ~15 km</div>` : ""}
    ${$("#p3-sites").checked ? `<div class="k"><span class="dot" style="background:${COLORS.p3};border-radius:2px"></span>Surveyed site (navigation module)</div>` : ""}
    ${S.route ? `<div class="k"><span class="dot" style="background:#4cd08a"></span>Planned rover route</div>` : ""}
    ${mode !== "regolith" ? `<div>${mode === "slope" ? "Slope" : "Elevation, relative"}</div><div class="bar" style="background:${mode === "slope" ? "linear-gradient(90deg,rgb(30,150,90),rgb(240,210,60),rgb(225,70,50))" : "linear-gradient(90deg,rgb(20,30,70),rgb(40,110,130),rgb(190,170,120),rgb(245,245,240))"}"></div>
      <div class="ends"><span>${mode === "slope" ? "0°" : "low"}</span><span>${mode === "slope" ? `over ${S.plan?.requirements.constraints.max_slope_deg ?? 15}° red` : "high"}</span></div>` : ""}`;
}
function planSites() {
  const P = S.plan; if (!P) return []; const by = new Map(); const recId = P.recommendation?.site.site_id;
  for (const o of P.candidates) { const k = o.site.site_id; if (!by.has(k)) by.set(k, { site: o.site, opts: [] }); by.get(k).opts.push(o); }
  return [...by.values()].map(({ site, opts }) => ({ id: site.site_id, name: nm(site), lat: site.latitude_deg, lon: site.longitude_deg, status: site.site_id === recId ? "recommended" : opts.some((o) => o.feasible) ? "feasible" : "rejected" }));
}
function refreshExplorer() {
  const ps = planSites(); explorer.sites = ps; explorer.render();
  if (!view) return;
  const markers = ps.map((s) => ({ id: s.id, lat: s.lat, lon: s.lon, label: esc(s.name), color: COLORS[s.status], kind: "plan" }));
  if ($("#artemis").checked && isLola(S.terrain)) for (const a of ARTEMIS_REGIONS) markers.push({ id: a.name, lat: a.lat, lon: a.lon, label: `NASA Artemis III region: ${esc(a.name)}`, color: "#F2C35B", kind: "artemis" });
  if ($("#features").checked) for (const f of S.terrain?.features || []) markers.push({ id: f.name, lat: f.lat_deg, lon: f.lon_deg, label: esc(f.name), color: "#cfd8e3", kind: "feature" });
  if ($("#p3-sites").checked) for (const s of S.p3Sites) markers.push({ id: s.site_id, lat: s.location.lat_deg, lon: s.location.lon_deg, label: esc(s.name.replace(/^Mock /, "")), color: COLORS.p3, kind: "p3" });
  if (S.dest) markers.push({ id: "dest", lat: S.dest.lat_deg, lon: S.dest.lon_deg, label: "Route destination", color: COLORS.dest, kind: "stop" });
  if (S.inspect) markers.push({ id: "inspect", lat: S.inspect.lat_deg, lon: S.inspect.lon_deg, label: "Inspected point", color: "#ffffff", kind: "stop" });
  const C = { shortest: [0.35, 0.66, 1, 0.95], balanced: [0.95, 0.72, 0.29, 0.95], gentle: [0.3, 0.82, 0.54, 0.95] };
  const paths = S.route ? S.route.alternatives.map((a) => ({ points: a.waypoints, color: a.alt_id === S.selAlt ? C[a.strategy] : C[a.strategy].map((v, i) => (i === 3 ? 0.45 : v)), width_m: a.alt_id === S.selAlt ? 320 : 160 })) : [];
  const artemisSquares = $("#artemis").checked && isLola(S.terrain) ? ARTEMIS_REGIONS.map((a) => { const c = project(a.lat, a.lon), h = 7500;
    const pts = [[-h, -h], [h, -h], [h, h], [-h, h], [-h, -h]].map(([dx, dy]) => unproject(c.x + dx, c.y + dy));
    return { points: pts, color: [0.95, 0.76, 0.36, 0.55], width_m: 160 }; }) : [];
  if (S.phase === "explore") { view.setMarkers(markers); view.setPaths([...artemisSquares, ...paths]); view.setRings([]); }
}
function loadPlanIntoMap() {
  if (!S.plan) return; explorer.setSlopeLimit(S.plan.requirements.constraints.max_slope_deg ?? 15);
  S.route = null; explorer.route = null; S.dest = null; explorer.destination = null;
  if (S.sel) selectSite(S.sel.siteId, S.sel.date, false); legend(); refreshExplorer();
}
function selectSite(id, date, fly = false) {
  const P = S.plan; if (!P) return; const opts = P.candidates.filter((o) => o.site.site_id === id); if (!opts.length) return;
  const o = opts.find((x) => x.visibility.date_utc === date) || opts.find((x) => x.feasible) || opts[0];
  S.sel = { siteId: id, date: o.visibility.date_utc }; explorer.selected = { id, layer: "plan" }; S.inspect = null;
  if (fly) focus(o.site.latitude_deg, o.site.longitude_deg); explorer.render();
  const rank = P.ranked_alternatives.findIndex((x) => optKey(x) === optKey(o)), s = o.site, v = o.visibility;
  const inCov = S.terrain?.inCoverage(s.latitude_deg, s.longitude_deg);
  $("#site-panel").innerHTML = `<h2>${esc(nm(s))}</h2><p class="sub">Site ${esc(s.site_id)}, ${latS(s.latitude_deg)}, ${lonE(s.longitude_deg)} ${badge(s.provenance.status)}</p>
    <dl class="kv"><dt>Elevation</dt><dd>${Math.round(s.elevation_m)} m</dd><dt>Slope</dt><dd>${s.slope_deg.toFixed(1)}°</dd><dt>Site source</dt><dd>${esc(s.provenance.source)}</dd>
      ${(() => { const t = S.terrain?.sample(s.latitude_deg, lon180(s.longitude_deg)); return t ? `<dt>Terrain grid here</dt><dd>${t.elevation_m.toFixed(0)} m, slope ${t.slope_deg.toFixed(1)}° ${tBadge(S.terrain)}</dd>` : ""; })()}</dl>
    ${isLola(S.terrain) && s.provenance.status === "MOCK" ? `<p class="note">The planner's site values are mock fixtures; the NASA LOLA line shows the real terrain at the same coordinates.</p>` : ""}
    <div class="datepick">${opts.map((x) => `<button type="button" data-d="${esc(x.visibility.date_utc)}" class="${x === o ? "on" : ""}">${esc(day(x.visibility.date_utc))}${x.feasible ? "" : ", rejected"}</button>`).join("")}</div>
    <dl class="kv"><dt>Sunlight</dt><dd style="color:var(--sun)">${h1(v.sunlight_hours)}</dd><dt>Earth in view</dt><dd style="color:var(--link)">${h1(v.earth_visible_hours)}</dd><dt>Longest blackout</dt><dd>${h1(v.max_blackout_hours)}</dd>
      ${o.route ? `<dt>Planner route</dt><dd>${fmtM(o.route.distance_m)}, ${o.route.accessible ? "accessible" : "blocked"}</dd>` : ""}
      <dt>Outcome</dt><dd>${o.feasible ? `Feasible, score ${o.score.toFixed(3)}${rank >= 0 ? `, rank ${rank + 1}` : ""}` : `<span style="color:var(--halt)">${esc(o.violations.join(", "))}</span>`}</dd>
      <dt>Measured by</dt><dd>${esc(v.provenance.source)} ${badge(v.provenance.status)}</dd>${v.provenance.uncertainty ? `<dt>Uncertainty</dt><dd>${esc(v.provenance.uncertainty)}</dd>` : ""}</dl>
    <p style="font-size:13px;color:var(--dust)">${esc(o.explanation)}</p>
    <div style="display:flex;gap:6px;flex-wrap:wrap">${inCov && view ? `<button class="btn" id="walk-here">LUNA WALK here</button>` : ""}${o.feasible && inCov ? `<button class="btn" id="sim-here">Simulate safety from here</button>` : ""}</div>
    ${!inCov ? `<p class="note" style="margin-top:10px">This site is outside the terrain grid (the dashed square), so 3D ground view, routes and the safety simulation are not available for it.</p>` : ""}`;
  $$(".datepick button").forEach((b) => b.addEventListener("click", () => { selectSite(id, b.dataset.d); S.sim = null; }));
  $("#walk-here")?.addEventListener("click", () => { setViewMode("3d"); enterWalk({ lat: s.latitude_deg, lon: s.longitude_deg, name: s.name }); });
  $("#sim-here")?.addEventListener("click", () => { runSim(); go("safety"); });
  renderRouteBox(); refreshExplorer();
}
function onGroundPick(ll, hit) {
  if (S.pick && S.phase === "safety") { setStop(S.pick, ll); return; }
  if (S.pick === "route-dest") { S.dest = { ...ll, label: hit?.id }; S.pick = null; document.body.classList.remove("picking"); explorer.pickMode = false; explorer.destination = ll; S.route = null; explorer.route = null; renderRouteBox(); refreshExplorer(); return; }
  if (S.phase !== "explore") return;
  const t = S.terrain?.sample(ll.lat_deg, ll.lon_deg); S.inspect = ll;
  const p3 = hit?.layer === "p3" ? S.p3Sites.find((x) => x.site_id === hit.id) : null;
  const feat = hit?.layer === "feature" ? hit.id : null;
  $("#site-panel").innerHTML = `<h2>${p3 ? esc(p3.name) : feat ? esc(feat) : "Inspected point"}</h2><p class="sub">${latS(ll.lat_deg)}, ${lonE(ll.lon_deg)}${p3 ? `, ${esc(p3.site_id)} ${badge(statusOf(p3.data_status))}` : ""}</p>
    ${t ? `<dl class="kv"><dt>Elevation</dt><dd>${t.elevation_m.toFixed(0)} m</dd><dt>Slope</dt><dd>${t.slope_deg.toFixed(2)}°</dd><dt>Distance from pole</dt><dd>${fmtM(Math.hypot(t.x, t.y))}</dd>
      <dt>Terrain source</dt><dd>${esc(S.terrain.source.name)} ${tBadge(S.terrain)}</dd><dt>Resolution</dt><dd>${S.terrain.cell} m grid</dd></dl>
      ${feat ? `<p style="font-size:13px;color:var(--dust)">IAU-named feature. Label position is the approximate centre.</p>` : ""}` : `<p class="note">Outside the terrain grid. No elevation or slope here.</p>`}
    ${p3 ? `<p style="font-size:13px;color:var(--dust)">${esc(p3.reason)} A navigation-module demo site, not a planner candidate.</p>` : ""}
    ${t && view ? `<button class="btn" id="walk-pt">LUNA WALK here</button>` : ""}`;
  $("#walk-pt")?.addEventListener("click", () => enterWalk({ lat: ll.lat_deg, lon: ll.lon_deg, name: p3 ? p3.name : feat || "inspected point" }));
  refreshExplorer();
}
function currentOption() { const P = S.plan; if (!P || !S.sel) return null; return P.candidates.find((o) => o.site.site_id === S.sel.siteId && o.visibility.date_utc === S.sel.date); }
function renderRouteBox() {
  const box = $("#route-box"), o = currentOption();
  if (!o) { box.innerHTML = `<h2>Rover route</h2><p class="note">Launch a mission analysis first, then plan a route from its landing site.</p>`; return; }
  const useApi = S.navOnline && S.terrain?.origin === "live";
  const engine = useApi ? "Person 3 navigation API" : `browser port of the Person 3 pathfinder on ${isLola(S.terrain) ? "NASA LOLA terrain" : "the bundled terrain snapshot"}`;
  box.innerHTML = `<h2>Rover route from ${esc(nm(o.site))}</h2>
    <p style="font-size:13px;color:var(--dust);margin:0 0 8px">Pick a destination on the map. Slope limit ${S.assumptions.rover.max_slope_deg}° (rover mobility). Engine: ${engine}.</p>
    <div style="display:flex;gap:6px;flex-wrap:wrap"><button class="btn" id="pick">${S.pick === "route-dest" ? "Click a destination" : "Choose destination"}</button>
      <select id="algo" class="btn" aria-label="Pathfinding algorithm"><option value="astar">A*</option><option value="dijkstra">Dijkstra</option></select>
      <button class="btn primary" id="plan-route" ${S.dest ? "" : "disabled"}>Plan route</button></div>
    ${S.dest ? `<p style="font-size:13px;margin:8px 0 0">Destination: ${latS(S.dest.lat_deg)}, ${lonE(S.dest.lon_deg)}${S.dest.label ? ` (${esc(S.dest.label)})` : ""}</p>` : ""}<div id="route-out"></div>`;
  $("#pick").onclick = () => { S.pick = S.pick === "route-dest" ? null : "route-dest"; explorer.pickMode = !!S.pick; document.body.classList.toggle("picking", !!S.pick); renderRouteBox(); };
  $("#plan-route").onclick = planRoute; if (S.route) renderRoute();
}
async function planRoute() {
  const o = currentOption(); if (!o || !S.dest) return; const out = $("#route-out"); out.innerHTML = `<p style="font-size:13px;color:var(--dust)">Planning…</p>`;
  const start = { lat_deg: o.site.latitude_deg, lon_deg: lon180(o.site.longitude_deg) }, lim = Math.min(45, Math.max(1, S.assumptions.rover.max_slope_deg)), algo = $("#algo").value;
  try {
    const useApi = S.navOnline && S.terrain?.origin === "live";
    const r = useApi ? await moonNav.routes(start, S.dest, lim, algo) : S.terrain.routes(start, S.dest, lim, { algorithm: algo });
    r.engine = useApi ? "Person 3 API" : `browser port of Person 3 pathfinder, ${isLola(S.terrain) ? "NASA LOLA terrain" : "bundled snapshot"}`;
    S.route = r; S.selAlt = r.alternatives[0]?.alt_id; explorer.route = r; explorer.selAlt = S.selAlt; explorer.render(); renderRoute(); refreshExplorer(); legend();
  } catch (e) { out.innerHTML = `<p class="note bad">${esc(e.message)}${String(e.message).includes("OUT_OF_COVERAGE") ? ". The terrain grid only covers the dashed square around the pole." : ""}</p>`; }
}
function renderRoute() {
  const r = S.route, out = $("#route-out"); if (!r || !out) return; const C = { shortest: "#5aa9ff", balanced: "#f2b84b", gentle: "#4cd08a" };
  out.innerHTML = r.alternatives.map((a) => `<div class="alt ${a.alt_id === S.selAlt ? "sel" : ""}" data-alt="${esc(a.alt_id)}" tabindex="0"><span class="sw2" style="background:${C[a.strategy]}"></span><b>${esc(a.strategy)}</b>
    <div class="st"><span>Distance ${fmtM(a.distance_m)}</span><span>Max slope ${a.max_slope_deg}°</span><span>Mean slope ${a.mean_slope_deg}°</span><span>Climb ${Math.round(a.elevation_gain_m)} m</span></div></div>`).join("")
    + `<p style="font-size:12.5px;color:var(--dust);margin-top:8px">${r.data_status === "REAL" && isLola(S.terrain) ? tBadge(S.terrain) : badge(statusOf(r.data_status))} ${esc(r.engine)}, operational validity ${esc(r.operational_validity)}. Routes are exploratory terrain-only estimates.</p>`;
  $$(".alt", out).forEach((d) => { const pick = () => { S.selAlt = d.dataset.alt; explorer.selAlt = S.selAlt; explorer.render(); renderRoute(); refreshExplorer(); };
    d.addEventListener("click", pick); d.addEventListener("keydown", (e) => e.key === "Enter" && pick()); });
}

/* ================= LUNA WALK ================= */
function enterWalk(at) {
  if (!view || !S.terrain) return; if (!S.terrain.inCoverage(at.lat, at.lon)) { toast("That point is outside the terrain grid."); return; }
  let yaw = 0; const tgt = S.phase === "safety" && S.stops ? S.stops.destination : null;
  if (tgt) { const a = project(at.lat, at.lon), b = project(tgt.lat, tgt.lon); yaw = Math.atan2(b.x - a.x, b.y - a.y); }
  view.setMode("walk", { lat: at.lat, lon: at.lon, yaw }); S.walkName = at.name;
  if (S.phase === "safety") drawSafety(); else refreshExplorer();
  document.body.classList.add("walking"); $("#walk-hud").hidden = false; walkHud({ lat_deg: at.lat, lon_deg: at.lon }); $("#gl").focus(); view.resize();
}
function exitWalk(silent) {
  if (!view || view.mode !== "walk") return; view.setMode("orbit"); document.body.classList.remove("walking"); $("#walk-hud").hidden = true;
  if (!silent) { if (S.phase === "safety") drawSafety(); else refreshExplorer(); } view.resize();
}
$("#walk-exit").addEventListener("click", () => exitWalk());
function walkHud(ll) {
  const t = S.terrain?.sample(ll.lat_deg, ll.lon_deg); if (!t) return;
  const head = ((view.walk.yaw * 180) / Math.PI % 360 + 360) % 360;
  $("#walk-where").textContent = `${S.walkName ? S.walkName + ", " : ""}${latS(ll.lat_deg)} ${lonE(ll.lon_deg)}, elevation ${t.elevation_m.toFixed(0)} m, local slope ${t.slope_deg.toFixed(1)}°, heading ${head.toFixed(0)}° from lon-0 meridian`;
}

/* ================= Safety simulation (Mission 05) ================= */
const VERDICT = {
  go: { t: "GO", p: "Every check passes under the current assumptions." },
  conditional: { t: "GO WITH CONDITIONS", p: "The mission can continue if the listed responses are applied." },
  nogo: { t: "NO-GO: STOP OR REASSESS", p: "At least one check fails with no safe workaround. Do not present this route as safe; change the plan." },
};
function simOption() { const o = currentOption(); return o && o.feasible ? o : S.plan?.recommendation; }
function buildStops(o) {
  const landing = { lat: o.site.latitude_deg, lon: lon180(o.site.longitude_deg), name: nm(o.site) };
  const d = defaultStops(S.terrain, landing, S.p3Sites); if (!d) return null;
  const lim = Math.min(S.assumptions.rover.max_slope_deg, S.assumptions.astronaut.max_slope_deg);
  const dest = snapToTraversable(S.terrain, S.customStops.destination || d.destination, lim);
  const smp = snapToTraversable(S.terrain, S.customStops.sample || d.sample, lim, dest);
  return { landing, deploy: d.deploy, destination: dest, sample: smp, list: [landing, d.deploy, dest, smp, { ...landing, name: "Landing site (return)" }] };
}
function runSim() {
  const o = simOption(); if (!o || !S.terrain) { S.sim = null; return; }
  if (!S.terrain.inCoverage(o.site.latitude_deg, o.site.longitude_deg)) { S.sim = { error: `${nm(o.site)} lies outside the terrain grid, so post-landing routes cannot be simulated. Select a site inside the dashed square.` }; return; }
  const stops = buildStops(o); if (!stops) { S.sim = { error: "No destination inside the terrain grid." }; return; }
  S.stops = stops;
  S.sim = simulate({ terrain: S.terrain, option: o, requirements: S.plan.requirements, stops: stops.list, assumptions: S.assumptions, scenarios: S.scenarios, actors: TYPES[S.plan.requirements.mission_type]?.actors || ["rover", "astronaut"] });
  S.sim.option = o;
}
function setStop(which, ll) {
  if (!S.terrain.inCoverage(ll.lat_deg, ll.lon_deg)) { toast("Pick a point inside the terrain grid."); return; }
  S.customStops[which] = { lat: ll.lat_deg, lon: ll.lon_deg, name: which === "destination" ? "Custom destination" : "Sample point" };
  S.pick = null; document.body.classList.remove("picking"); runSim(); renderSafety();
}
function renderSafety() {
  const side = $("#sf-side"); if (!S.plan) return;
  if (!S.sim) runSim(); const R = S.sim;
  if (!R || R.error) { side.innerHTML = `<p class="kicker">Mission 05</p><h1 id="h-safety">Safety and continuity</h1><p class="note bad">${esc(R?.error || "Terrain is still loading.")}</p>`; return; }
  const A = R.assumptions, o = R.option, st = S.stops;
  const lim = Math.min(A.rover.max_slope_deg, A.astronaut.max_slope_deg);
  const snapNote = (s) => (s.snapped_m > 0 ? `<small style="color:var(--sun)">Moved ${fmtM(s.snapped_m)} from the chosen point to ground under ${(0.7 * lim).toFixed(1)}°</small>` : s.snapped_m === null ? `<small style="color:var(--halt)">No drivable ground within 4 km of this point</small>` : "");
  const stopRow = (s, label, key) => `<li><span><b>${esc(label)}</b><small>${esc(s.name)}, ${latS(s.lat)} ${lonE(s.lon)}</small>${snapNote(s)}</span>${key ? `<button class="btn" data-pick="${key}">${S.pick === key ? "Click the map" : "Move"}</button>` : "<span></span>"}</li>`;
  const tl = timelineSvg(R);
  side.innerHTML = `<p class="kicker">Mission 05</p><h1 id="h-safety">Safety and continuity</h1>
    <p style="color:var(--dust);font-size:13px;margin:0">Can the crew and rover finish the mission after landing at <b style="color:var(--regolith)">${esc(nm(o.site))}</b> on ${esc(day(o.visibility.date_utc))}? Decision support, not a certified safety system.</p>
    <div class="verdict ${R.overall}"><b>${VERDICT[R.overall].t}</b><p>${VERDICT[R.overall].p}</p>
      <div class="actors">${["rover", "astronaut"].map((a) => `<span class="chip ${R.verdicts[a]}">${a === "rover" ? "Rover" : "Astronauts"}: ${VERDICT[R.verdicts[a]].t.split(":")[0].toLowerCase()}${R.actors.includes(a) ? "" : " (advisory)"}</span>`).join("")}</div></div>
    <h2>Mission route</h2><ol class="stops">${stopRow(st.landing, "Landing zone")}${stopRow(st.deploy, "Rover deployment")}${stopRow(st.destination, "Exploration destination", "destination")}${stopRow(st.sample, "Sample collection", "sample")}${stopRow(st.landing, "Return to landing zone")}</ol>
    <p class="hint">Crew rides the rover to the destination and walks the sample loop.</p>
    <div style="display:flex;gap:6px;margin-top:10px;flex-wrap:wrap"><button class="btn" id="walk-route">LUNA WALK from the landing zone</button>${S.customStops.destination || S.customStops.sample ? `<button class="btn" id="reset-stops">Reset route</button>` : ""}</div>
    <h2>Hazard scenarios</h2><div class="scen">${Object.entries(SCENARIOS).map(([k, s]) => `<button type="button" data-scen="${k}" aria-pressed="${!!S.scenarios[k]}">${esc(s.label)}<small>${esc(s.what)}</small></button>`).join("")}</div>
    <p class="hint">Scenarios are simulated events, not detected conditions. Toggle one to see the warning, the response and the recalculated plan.</p>
    <h2>Detected hazards (${R.hazards.length})</h2>${R.hazards.map(hazardCard).join("") || `<p style="color:var(--dust)">No hazards under the current assumptions.</p>`}
    <h2>Rover traverse</h2><div class="nums"><div><b>${R.totals.km ? R.totals.km.toFixed(1) : "–"} km</b>Loop distance</div><div><b>${R.totals.drive_h ? R.totals.drive_h.toFixed(1) : "–"} h</b>Driving</div>
      <div><b>${Number.isFinite(R.totals.total_h) ? R.totals.total_h.toFixed(1) : "–"} h</b>Of ${R.duration} h stay</div><div><b>${Math.round(R.totals.drive_wh ?? 0)} Wh</b>Drive energy</div>
      <div><b>${Math.round(R.totals.systems_wh ?? 0)} Wh</b>Systems energy</div><div><b>${R.totals.min_soc_wh != null ? Math.max(0, Math.round(R.totals.min_soc_wh)) : "–"} Wh</b>Lowest usable charge</div></div>
    ${tl}
    <table class="legs" style="margin-top:10px"><thead><tr><th>Leg</th><th>Route</th><th>Dist.</th><th>Max slope</th><th>Energy</th></tr></thead><tbody>
      ${R.rover.map((l) => l.ok ? l.alts.map((a) => `<tr class="${a.strategy === l.strategy ? "chosen" : ""}"><td>${a.strategy === l.strategy ? `${esc(l.from)} to ${esc(l.to)}` : ""}</td><td>${a.strategy}${a.strategy === l.strategy ? " (used)" : ""}</td><td>${(a.distance_m / 1000).toFixed(2)} km</td><td>${a.max_slope.toFixed(1)}°</td><td>${Math.round(a.energy_wh)} Wh</td></tr>`).join("")
        : `<tr><td>${esc(l.from)} to ${esc(l.to)}</td><td colspan="4" style="color:var(--halt)">no route</td></tr>`).join("")}</tbody></table>
    <h2>Astronaut EVA</h2><div class="nums"><div><b>${R.astroTotals.km.toFixed(1)} km</b>Walking loop</div><div><b>${R.astroTotals.h.toFixed(1)} h</b>EVA incl. ${A.sample_h} h sampling</div><div><b>${R.astro.filter((l) => l.ok).length ? Math.max(...R.astro.filter((l) => l.ok).map((l) => l.max_slope)).toFixed(1) : "–"}°</b>Steepest step</div></div>
    <details class="block" style="padding:12px 0 0;border:0"><summary style="cursor:pointer;font-family:var(--display)">Planning assumptions (editable)</summary><div class="assume" id="assume">
      ${[["rover.speed_mps", "Rover speed, m/s"], ["rover.max_slope_deg", "Rover max slope, °"], ["rover.battery_wh", "Battery, Wh"], ["rover.reserve_pct", "Battery reserve, %"], ["rover.drive_wh_per_km", "Drive energy, Wh/km"], ["rover.climb_wh_per_m", "Climb energy, Wh/m"], ["rover.hotel_w", "Systems load, W"], ["rover.solar_w", "Solar array, W"], ["rover.autonomy_h", "Rover autonomy without contact, h"], ["astronaut.walk_kmh", "Walking speed, km/h"], ["astronaut.max_slope_deg", "Max walking slope, °"], ["astronaut.max_eva_km", "Max EVA walk, km"], ["astronaut.max_eva_h", "Max EVA, h"], ["sample_h", "Sampling time, h"]]
        .map(([k, l]) => `<label>${l}<input type="number" step="any" data-k="${k}" value="${k.split(".").reduce((o2, p) => o2[p], S.assumptions)}" /></label>`).join("")}</div></details>
    <p class="prov">Measurements: sunlight ${R.option.visibility.sunlight_hours.toFixed(1)} h, Earth visible ${R.option.visibility.earth_visible_hours.toFixed(1)} h, longest blackout ${R.option.visibility.max_blackout_hours.toFixed(1)} h from ${esc(R.option.visibility.provenance.source)} ${badge(R.option.visibility.provenance.status)}. Terrain: ${esc(S.terrain.source.name)} ${tBadge(S.terrain)}, ${S.terrain.cell} m grid, ${tOrigin(S.terrain)}. Routes: browser port of the Person 3 pathfinder (A*, slope-blocked cells). Energy, speed and EVA limits are your planning assumptions above, not telemetry.</p>`;
  $$("[data-scen]", side).forEach((b) => b.addEventListener("click", () => { const k = b.dataset.scen; S.scenarios[k] = !S.scenarios[k]; if (!S.scenarios[k]) delete S.scenarios[k]; runSim(); renderSafety(); }));
  $$("[data-pick]", side).forEach((b) => b.addEventListener("click", () => { S.pick = S.pick === b.dataset.pick ? null : b.dataset.pick; document.body.classList.toggle("picking", !!S.pick); renderSafety(); if (S.pick) toast("Click the 3D terrain to place it."); }));
  $("#reset-stops")?.addEventListener("click", () => { S.customStops = {}; runSim(); renderSafety(); });
  $("#walk-route").addEventListener("click", () => enterWalk({ lat: st.landing.lat, lon: st.landing.lon, name: "Landing zone" }));
  $$("#assume input", side).forEach((inp) => inp.addEventListener("change", () => { const v = +inp.value; if (!Number.isFinite(v) || v < 0) return; const [a, b] = inp.dataset.k.split(".");
    if (b) S.assumptions[a][b] = v; else S.assumptions[a] = v; runSim(); renderSafety(); $(`#assume input[data-k="${inp.dataset.k}"]`)?.closest("details")?.setAttribute("open", ""); }));
  drawSafety(); renderDossierQuiet();
}
function renderDossierQuiet() { if (S.phase !== "discover") renderDossier(); }
function hazardCard(h) {
  return `<div class="haz ${h.severity}"><h3><span class="sev ${h.severity}">${{ block: "Blocking", warn: "Warning", info: "Advisory" }[h.severity]}</span>${esc(h.title)}</h3>
    <div class="actors" style="margin:2px 0 4px">${h.affects.map((a) => `<span class="chip ${a}">${a === "rover" ? "Rover" : "Astronauts"}</span>`).join("")}</div>
    <p><span class="lab">Why: </span>${esc(h.reason)}</p><p><span class="lab">Response: </span>${esc(h.response)}</p>${h.recalc ? `<p class="recalc">Recalculated: ${esc(h.recalc)}</p>` : ""}</div>`;
}
function timelineSvg(R) {
  const W = 430, H = 56, D = Math.max(R.duration, R.totals.total_h || 0), x = (h) => 6 + (h / D) * (W - 12);
  const col = { "Rover deployment": "var(--dust)", "Sample collection": "var(--link)", "Solar recharge": "var(--sun)" };
  const segs = R.timeline.map((s) => `<rect x="${x(s.start)}" y="10" width="${Math.max(1.5, x(s.end) - x(s.start))}" height="18" rx="3" fill="${col[s.label] || "var(--ground)"}"><title>${esc(s.label)}: ${s.start.toFixed(1)} to ${s.end.toFixed(1)} h</title></rect>`).join("");
  return `<svg class="tl" viewBox="0 0 ${W} ${H}" role="img" aria-label="Operations timeline against the surface stay">
    <rect x="6" y="10" width="${W - 12}" height="18" rx="3" fill="var(--line-soft)"/>${segs}
    <line x1="${x(R.duration)}" x2="${x(R.duration)}" y1="4" y2="34" stroke="var(--halt)" stroke-width="2"/><text x="${Math.min(W - 70, x(R.duration) + 4)}" y="46" fill="var(--dust)" font-size="10.5">stay ends ${R.duration} h</text>
    <text x="6" y="46" fill="var(--dust)" font-size="10.5">landing</text></svg>
    <div class="contrib-keys"><span><i style="background:var(--ground)"></i>Driving</span><span><i style="background:var(--link)"></i>Sampling</span><span><i style="background:var(--sun)"></i>Recharge</span></div>`;
}
function drawSafety() {
  if (!view || !S.sim || S.sim.error || S.phase !== "safety") return; const R = S.sim, st = S.stops;
  const markers = [{ id: "L", lat: st.landing.lat, lon: st.landing.lon, label: "Landing zone", color: COLORS.recommended, kind: "plan" },
    { id: "D", lat: st.destination.lat, lon: st.destination.lon, label: `Destination: ${esc(st.destination.name)}`, color: COLORS.dest, kind: "stop" },
    { id: "S", lat: st.sample.lat, lon: st.sample.lon, label: "Sample collection", color: COLORS.sample, kind: "stop" }];
  const paths = [];
  R.rover.forEach((l) => l.ok && paths.push({ points: l.waypoints, color: [0.66, 0.79, 0.6, 0.95], width_m: 300, walkWidth: 0.5 }));
  R.astro.forEach((l) => l.ok && paths.push({ points: l.waypoints, color: [0.41, 0.78, 0.93, 0.95], width_m: 170, walkWidth: 0.35 }));
  if (R.ridge) paths.push({ points: [R.ridge.a, R.ridge.b], color: [0.94, 0.48, 0.42, 0.75], width_m: 700, walkWidth: 700 });
  view.setMarkers(markers); view.setPaths(paths); view.setRings(R.obstacle ? [{ x: R.obstacle.x, y: R.obstacle.y, radius_m: R.obstacle.radius_m, color: [0.94, 0.48, 0.42, 0.9] }] : []);
  if (!drawSafety.framed || drawSafety.framed !== st.landing.name) { drawSafety.framed = st.landing.name; const a = project(st.landing.lat, st.landing.lon), b = project(st.destination.lat, st.destination.lon);
    const mid = unproject((a.x + b.x) / 2, (a.y + b.y) / 2); if (view.mode !== "walk") view.flyTo(mid.lat_deg, mid.lon_deg, Math.max(22000, Math.hypot(a.x - b.x, a.y - b.y) * 2.2)); }
  $("#sf-legend").innerHTML = `<div class="k"><span class="dot" style="background:var(--ground)"></span>Rover route</div><div class="k"><span class="dot" style="background:var(--link)"></span>Astronaut EVA path</div>
    ${R.obstacle || R.ridge ? `<div class="k"><span class="dot" style="background:var(--halt)"></span>Simulated hazard zone</div>` : ""}<div class="k"><span class="dot" style="background:var(--sun)"></span>Landing zone</div>`;
}

/* ================= services + terrain ================= */
function setService(which, ok, label) { const b = $(`#svc-${which}`); b.classList.toggle("ok", ok); b.classList.toggle("down", !ok);
  b.title = `${which === "planner" ? "Mission planner" : "Moon navigation"} at ${which === "planner" ? CONFIG.apiBase : CONFIG.navBase}: ${label || (ok ? "online" : "offline")}`;
  led(which, ok ? "ok" : "down", label || (ok ? "online" : "offline")); }
async function checkPlanner() { try { const h = await planner.health(); setService("planner", h.status === "ok", CONFIG.recorded ? "recorded NASA runs" : undefined); return true; } catch { setService("planner", false); return false; } }
async function checkNav() {
  try { await moonNav.health(); S.navOnline = true; setService("nav", true); } catch { S.navOnline = false; setService("nav", false, "offline, using snapshot"); }
  try {
    const { terrain, sites, sitesMeta } = await loadTerrain(); S.terrain = terrain; S.p3Sites = sites; S.p3Meta = sitesMeta;
    led("terrain", terrain.status === "MOCK" ? "warn" : "ok", isLola(terrain) ? `NASA LOLA, ${terrain.cell} m` : `${terrain.status === "MOCK" ? "mock fixture" : terrain.status}, ${terrain.origin === "live" ? "live" : "bundled snapshot"}`);
    if (isLola(terrain)) { $("#exag").value = 1.5; $("#exag-out").textContent = "×1.5"; view?.setExaggeration(1.5);
      // Person 3's demo sites were placed for its synthetic terrain; they mean nothing on real LOLA terrain.
      $("#p3-sites").checked = false; explorer.layers.p3Sites = false; $("#p3-wrap").hidden = true; }
    view?.setTerrain(terrain); view?.setColorMode($("#terrain-mode .on")?.dataset.mode || "regolith");
    explorer.setGrid({ cols: terrain.cols, rows: terrain.rows, cell_size_m: terrain.cell, origin_x_m: terrain.ox, origin_y_m: terrain.oy, elevation_m: terrain.elev, slope_deg: terrain.slope, terrain_source: terrain.source, data_status: terrain.status });
    explorer.setTerrainMode("none");
    explorer.p3Sites = sites.map((s) => ({ id: s.site_id, name: s.name, lat: s.location.lat_deg, lon: s.location.lon_deg }));
    $("#dest-select").innerHTML = `<option value="auto">Automatic: 5 km toward the nearest named crater</option>` + (terrain.features || []).filter((f) => terrain.inCoverage(f.lat_deg, f.lon_deg)).map((f) => `<option value='${JSON.stringify({ lat: f.lat_deg, lon: f.lon_deg, name: f.name }).replace(/'/g, "&#39;")}'>${esc(f.name)} (NASA LOLA terrain)</option>`).join("")
      + (isLola(terrain) ? "" : sites.map((s) => `<option value='${JSON.stringify({ lat: s.location.lat_deg, lon: s.location.lon_deg, name: s.name.replace(/^Mock /, "") })}'>${esc(s.name)}</option>`).join(""))
      + (isLola(terrain) ? ARTEMIS_REGIONS.filter((a) => terrain.inCoverage(a.lat, a.lon)).map((a) => `<option value='${JSON.stringify({ lat: a.lat, lon: a.lon, name: "Artemis III region: " + a.name })}'>NASA Artemis III region: ${esc(a.name)}</option>`).join("") : "");
    $("#nav-banner").className = "note";
    $("#nav-banner").innerHTML = `Terrain: ${esc(terrain.source.name)} ${tBadge(terrain)}, ${terrain.cell} m grid covering ${((terrain.maxX - terrain.ox) / 1000).toFixed(0)} × ${((terrain.maxY - terrain.oy) / 1000).toFixed(0)} km around the pole. ${isLola(terrain) ? `Real elevations measured by NASA's Lunar Reconnaissance Orbiter laser altimeter (${esc(terrain.source.observations || "")}), ${esc(terrain.source.version || "")}. Slopes computed from these heights.` : terrain.origin === "live" ? "Loaded live from the navigation module." : `Navigation module offline at ${esc(CONFIG.navBase)}, so this is the bundled snapshot of its fixture.`} ${terrain.status === "MOCK" ? "Synthetic, not NASA data." : ""}`;
    if (S.plan) { if (S.plan.recommendation && !S.sim) runSim(); renderDossierQuiet(); }
  } catch (e) { led("terrain", "down", "unavailable"); $("#nav-banner").className = "note bad"; $("#nav-banner").textContent = `Terrain could not be loaded: ${e.message}`; }
  refreshExplorer(); legend(); renderRouteBox();
  if (!S.plan) $("#site-panel").innerHTML = `<p class="note">Launch a mission analysis to place the planner's candidate landing sites here. Meanwhile, click anywhere on the terrain to inspect elevation and slope.</p>`;
}
$("#svc-planner").onclick = async () => toast((await checkPlanner()) ? `Planner online at ${CONFIG.apiBase}` : `Planner offline at ${CONFIG.apiBase}. Add ?api=URL to point elsewhere.`);
$("#svc-nav").onclick = async () => { await checkNav(); toast(S.navOnline ? `Navigation online at ${CONFIG.navBase}` : `Navigation offline at ${CONFIG.navBase}. Using the bundled terrain snapshot.`); };

let recordedAt = "";
if (CONFIG.recorded) {
  const bar = document.createElement("div"); bar.className = "recorded-bar"; bar.setAttribute("role", "note");
  bar.innerHTML = `<b>Public demo.</b> Mission plans are real runs recorded from the backend on NASA LOLA + JPL Horizons data. Live planning: <a href="${REPO_URL}" target="_blank" rel="noopener">download</a> and run RUN.bat.`;
  document.body.append(bar);
  recordedRuns().then((r) => { recordedAt = (r.meta?.recorded_utc || "").replace("T", " ").replace("+00:00", " UTC"); }).catch(() => {});
}
applyPreset("science"); renderPipeline(); go("cabin"); checkPlanner(); checkNav();
window.__luna = { S, explorer, view, go, runSim };
