// Mission Safety & Continuity simulation. DECISION SUPPORT ONLY, not a certified safety system.
// Inputs that are measurements come from the backend plan (site, sunlight, Earth visibility, blackout)
// and the terrain grid (Person 3 fixture, MOCK). Vehicle and crew figures are the user's PLANNING
// ASSUMPTIONS, shown and editable in the UI. Every number below is a deterministic calculation.
import { project, unproject } from "./geo.js";

export const DEFAULT_ASSUMPTIONS = {
  rover: { max_slope_deg: 15, speed_mps: 0.2, battery_wh: 1500, reserve_pct: 20, drive_wh_per_km: 100, climb_wh_per_m: 0.6, hotel_w: 60, solar_w: 150, autonomy_h: 24 },
  astronaut: { max_slope_deg: 12, walk_kmh: 2.0, max_eva_km: 8, max_eva_h: 7 },
  sample_h: 2,
};
export const SCENARIOS = {
  steep: { label: "Steep slope blocks the route", affects: ["rover", "astronaut"], what: "A 14 km steep ridge across the outbound route, and loose regolith halves slope limits" },
  crater: { label: "Crater or obstacle ahead", affects: ["rover", "astronaut"], what: "No-go zone of 2.5 km radius placed on the outbound route" },
  battery: { label: "Insufficient rover battery", affects: ["rover"], what: "Battery capacity reduced to 30% (cell failure)" },
  blackout: { label: "Communication blackout", affects: ["rover", "astronaut"], what: "Extra 30 h loss of Earth contact during operations" },
  slow: { label: "Route too long for the mission", affects: ["rover"], what: "Drive speed reduced to 35% (wheel slip)" },
};
const STRATS = ["balanced", "gentle", "shortest"];

function legStats(alt, a, opts) {
  const km = alt.distance_m / 1000;
  const energy = km * a.rover.drive_wh_per_km * (1 + alt.mean_slope_deg / opts.limit) + alt.elevation_gain_m * a.rover.climb_wh_per_m;
  return { strategy: alt.strategy, distance_m: alt.distance_m, straight_m: alt.straight_line_distance_m, max_slope: alt.max_slope_deg, mean_slope: alt.mean_slope_deg,
    gain_m: alt.elevation_gain_m, detour: alt.straight_line_distance_m > 0 ? alt.distance_m / alt.straight_line_distance_m : 1, energy_wh: energy, waypoints: alt.waypoints, alts: null };
}

function planLegs(terrain, stops, limit, a, blocked, pick = "balanced") {
  const legs = [];
  for (let k = 0; k < stops.length - 1; k++) {
    const from = stops[k], to = stops[k + 1];
    try {
      const out = terrain.routes({ lat_deg: from.lat, lon_deg: from.lon }, { lat_deg: to.lat, lon_deg: to.lon }, limit, { strategies: STRATS, blocked });
      const all = out.alternatives.map((x) => legStats(x, a, { limit }));
      const chosen = all.find((x) => x.strategy === pick) || all[0];
      legs.push({ from: from.name, to: to.name, ok: true, ...chosen, alts: all });
    } catch (e) { legs.push({ from: from.name, to: to.name, ok: false, error: e.message, code: e.code }); }
  }
  return legs;
}

export function simulate({ terrain, option, requirements, stops, assumptions, scenarios = {}, actors }) {
  const A = structuredClone(assumptions); const v = option.visibility; const dur = requirements.duration_hours;
  const notes = [];
  if (scenarios.steep) { A.rover.max_slope_deg /= 2; A.astronaut.max_slope_deg /= 2; }
  if (scenarios.battery) A.rover.battery_wh *= 0.3;
  if (scenarios.slow) A.rover.speed_mps *= 0.35;
  const blackout = v.max_blackout_hours + (scenarios.blackout ? 30 : 0);
  const sunFrac = Math.min(1, v.sunlight_hours / dur);
  let blocked = null, obstacle = null;
  // stops: [landing, deploy, destination, sample, landing]
  const covered = stops.every((s) => terrain.inCoverage(s.lat, s.lon));
  if (!covered) return { error: "Part of the traverse lies outside the terrain coverage (the dashed square). Pick a destination and sample point inside it, or choose a landing site inside the coverage." };
  let ridge = null;
  if (scenarios.crater || scenarios.steep) {
    const base = planLegs(terrain, [stops[1], stops[2]], A.rover.max_slope_deg, A, null)[0];
    if (base.ok) { const wp = base.waypoints; const mid = wp[Math.floor(wp.length / 2)]; const p = project(mid.lat_deg, mid.lon_deg);
      blocked = new Uint8Array(terrain.cols * terrain.rows);
      if (scenarios.crater) { let r = 2500; for (const s of stops) { const q = project(s.lat, s.lon); const d = Math.hypot(q.x - p.x, q.y - p.y); if (d < r + 300) r = Math.max(600, d - 300); }
        obstacle = { x: p.x, y: p.y, radius_m: r, center: unproject(p.x, p.y) }; blocked = terrain.obstacleMask(p.x, p.y, r); }
      if (scenarios.steep) { const a = project(stops[1].lat, stops[1].lon), b = project(stops[2].lat, stops[2].lon); const L = Math.hypot(b.x - a.x, b.y - a.y) || 1;
        const nx = -(b.y - a.y) / L, ny = (b.x - a.x) / L; const c = { x: a.x + (b.x - a.x) * 0.45, y: a.y + (b.y - a.y) * 0.45 };
        ridge = { a: unproject(c.x - nx * 7000, c.y - ny * 7000), b: unproject(c.x + nx * 7000, c.y + ny * 7000), half_width_m: 350 };
        terrain.bandMask(c.x - nx * 7000, c.y - ny * 7000, c.x + nx * 7000, c.y + ny * 7000, 350, blocked); } }
  }
  const unmasked = blocked ? planLegs(terrain, stops.slice(1), assumptions.rover.max_slope_deg, A, null) : null;
  // ---------- rover ----------
  const roverStops = stops.slice(1); // deploy -> destination -> sample -> landing
  let rover = planLegs(terrain, roverStops, A.rover.max_slope_deg, A, blocked);
  const hazards = [];
  const roverBlocked = rover.filter((l) => !l.ok);
  const sumLegs = (legs) => legs.filter((l) => l.ok).reduce((o, l) => ({ km: o.km + l.distance_m / 1000, wh: o.wh + l.energy_wh, gain: o.gain + l.gain_m }), { km: 0, wh: 0, gain: 0 });
  const opsTime = (legs) => sumLegs(legs).km * 1000 / A.rover.speed_mps / 3600 + A.sample_h;
  const net = A.rover.solar_w * sunFrac - A.rover.hotel_w; // W while parked
  /** Sequential state-of-charge simulation: start at usable capacity, drain per leg (drive energy + systems − solar),
   *  recharge while parked at the sample point. Returns needed recharge hours inserted at the sample point. */
  const socRun = (legs) => {
    let soc = usable, minSoc = usable, recharge = 0, drive = 0, sys = 0;
    legs.forEach((l, k) => { if (!l.ok) return; const h = l.distance_m / A.rover.speed_mps / 3600;
      const use = l.energy_wh + A.rover.hotel_w * h - A.rover.solar_w * sunFrac * h; drive += l.energy_wh; sys += A.rover.hotel_w * h;
      if (soc - use < 0 && k === legs.length - 1 && net > 0) { const need = use - soc; recharge = need / net; soc += need; }
      soc -= use; minSoc = Math.min(minSoc, soc);
      if (k === 1) soc = Math.min(usable, soc + Math.max(0, net) * A.sample_h); });
    return { minSoc, recharge, drive, sys };
  };
  const energyNeed = (legs) => usable - socRun(legs).minSoc;
  const usable = A.rover.battery_wh * (1 - A.rover.reserve_pct / 100);

  for (const l of roverBlocked) hazards.push({ id: "slope-block", severity: "block", affects: ["rover"], title: `No rover route from ${l.from} to ${l.to}`,
    reason: `Every path between these points crosses terrain steeper than the rover limit of ${A.rover.max_slope_deg.toFixed(1)}°${blocked ? " or the obstacle zone" : ""}.`,
    response: "Choose a different destination or sample point, or land at a site with gentler access. The planner will not raise the slope limit for you." });

  let before = null;
  if (!roverBlocked.length) {
    const baseKm = sumLegs(rover).km, baseWh = energyNeed(rover), baseH = opsTime(rover);
    // try to reduce energy / slope exposure with alternative strategies per leg
    if (baseWh > usable || rover.some((l) => l.max_slope > 0.8 * A.rover.max_slope_deg)) {
      before = { km: baseKm, wh: baseWh, h: baseH };
      rover = rover.map((l) => { const best = [...l.alts].sort((p, q) => (p.max_slope > 0.8 * A.rover.max_slope_deg) - (q.max_slope > 0.8 * A.rover.max_slope_deg) || p.energy_wh - q.energy_wh)[0];
        return { ...l, ...best, alts: l.alts, switched: best.strategy !== l.strategy ? `${l.strategy} to ${best.strategy}` : null }; });
    }
  }
  const tot = { ...sumLegs(rover), drive_h: sumLegs(rover).km * 1000 / A.rover.speed_mps / 3600 };
  tot.ops_h = tot.drive_h + A.sample_h; tot.energy_need_wh = energyNeed(rover); tot.usable_wh = usable;
  tot.recharge_h = 0; tot.hold_h = 0;

  if (!roverBlocked.length) {
    if (unmasked && unmasked.every((l) => l.ok)) { const u = unmasked.reduce((o, l) => ({ km: o.km + l.distance_m / 1000 }), { km: 0 });
      const uh = u.km * 1000 / assumptions.rover.speed_mps / 3600;
      hazards.push({ id: scenarios.crater ? "crater" : "ridge", severity: "warn", affects: ["rover", "astronaut"],
        title: scenarios.crater && scenarios.steep ? "Simulated crater and steep ridge on the route" : scenarios.crater ? "Crater ahead on the outbound route (simulated)" : "Steep ridge blocks the direct route (simulated)",
        reason: scenarios.crater ? `A ${(obstacle.radius_m / 1000).toFixed(1)} km no-go zone was placed on the planned path near ${Math.abs(obstacle.center.lat_deg).toFixed(3)}° S.` : "A 14 km band steeper than any vehicle limit now crosses the outbound route, and slope limits are halved for loose regolith.",
        response: `Rerouted around it with the ${rover.filter((l) => l.ok).map((l) => l.strategy)[0] || "available"} strategy. Crew must stay clear of the hazard zone.`,
        recalc: `Distance ${u.km.toFixed(2)} km to ${tot.km.toFixed(2)} km, drive time ${uh.toFixed(1)} h to ${tot.drive_h.toFixed(1)} h at ${(A.rover.speed_mps).toFixed(2)} m/s.` }); }
    const switched = rover.filter((l) => l.switched);
    if (switched.length && before) hazards.push({ id: "reroute", severity: "warn", affects: ["rover"], title: "Rover route changed to reduce risk",
      reason: `The first plan ${before.wh > usable ? "needed more energy than the usable battery" : "came within 80% of the slope limit"}.`,
      response: switched.map((l) => `${l.from} to ${l.to}: ${l.switched} route`).join("; ") + ".",
      recalc: `Distance ${before.km.toFixed(2)} km to ${tot.km.toFixed(2)} km, energy ${Math.round(before.wh)} Wh to ${Math.round(tot.energy_need_wh)} Wh, time ${before.h.toFixed(1)} h to ${tot.ops_h.toFixed(1)} h.` });
    for (const l of rover) {
      if (l.detour > 1.25) hazards.push({ id: "detour", severity: "warn", affects: ["rover"], title: `Obstacle forces a detour: ${l.from} to ${l.to}`,
        reason: `The route is ${l.detour.toFixed(2)}× the straight-line distance (${(l.straight_m / 1000).toFixed(1)} km), meaning steep ground or a crater sits on the direct line${obstacle ? " (simulated obstacle)" : ""}.`,
        response: `Follow the ${l.strategy} route around it. ${l.alts.length > 1 ? "Alternatives: " + l.alts.filter((x) => x.strategy !== l.strategy).map((x) => `${x.strategy} ${(x.distance_m / 1000).toFixed(1)} km, max ${x.max_slope.toFixed(1)}°`).join("; ") + "." : ""}` });
      if (l.max_slope > 0.8 * A.rover.max_slope_deg) hazards.push({ id: "near-limit", severity: "warn", affects: ["rover"], title: `Slope near the rover limit: ${l.from} to ${l.to}`,
        reason: `Steepest cell on the route is ${l.max_slope.toFixed(1)}°, against a ${A.rover.max_slope_deg.toFixed(1)}° limit.`, response: "Drive this section at reduced speed with hazard cameras active, or pick the gentle route." });
    }
    const soc = socRun(rover); tot.drive_wh = soc.drive; tot.systems_wh = soc.sys; tot.min_soc_wh = soc.minSoc;
    if (soc.minSoc < 0 || soc.recharge > 0) {
      tot.recharge_h = soc.minSoc < 0 ? Infinity : soc.recharge;
      hazards.push({ id: "battery", severity: Number.isFinite(tot.recharge_h) ? "warn" : "block", affects: ["rover"], title: "Rover battery is insufficient for the full traverse",
        reason: `The traverse draws ${Math.round(soc.drive)} Wh for driving and ${Math.round(soc.sys)} Wh for systems, offset by solar at ${(sunFrac * 100).toFixed(0)}% sunlit time, but only ${Math.round(usable)} Wh is usable after the ${A.rover.reserve_pct}% reserve.`,
        response: Number.isFinite(tot.recharge_h) ? `Park at the sample point and recharge for ${tot.recharge_h.toFixed(1)} h before the return drive (net +${net.toFixed(0)} W while parked).` : "The battery runs out on the way out, before any recharge stop. Shorten the traverse, add battery, or choose a closer destination.",
        recalc: Number.isFinite(tot.recharge_h) ? `Operations time ${tot.ops_h.toFixed(1)} h to ${(tot.ops_h + tot.recharge_h).toFixed(1)} h; lowest charge ${Math.round(Math.max(0, soc.minSoc))} Wh.` : null });
    }
    if (blackout > A.rover.autonomy_h) {
      tot.hold_h = blackout;
      hazards.push({ id: "blackout-rover", severity: "warn", affects: ["rover"], title: "Expected communication blackout longer than rover autonomy",
        reason: `Longest loss of Earth contact is ${blackout.toFixed(1)} h${scenarios.blackout ? " (includes 30 h simulated)" : ""}, beyond the rover's ${A.rover.autonomy_h} h autonomous limit. The visibility service gives the blackout length, not its start time.`,
        response: "Park in a safe spot and hold during the blackout, then resume.", recalc: `Adds ${blackout.toFixed(1)} h of hold time.` });
    }
    const total = tot.ops_h + (Number.isFinite(tot.recharge_h) ? tot.recharge_h : 0) + tot.hold_h; tot.total_h = total;
    if (total > dur) hazards.push({ id: "time", severity: "block", affects: ["rover"], title: "Traverse cannot finish within the mission duration",
      reason: `Driving ${tot.drive_h.toFixed(1)} h + sampling ${A.sample_h} h${tot.recharge_h && Number.isFinite(tot.recharge_h) ? ` + recharge ${tot.recharge_h.toFixed(1)} h` : ""}${tot.hold_h ? ` + blackout hold ${tot.hold_h.toFixed(1)} h` : ""} = ${total.toFixed(1)} h, but the surface stay is ${dur} h.${Number.isFinite(tot.recharge_h) ? "" : " No solar recharge is possible, so the battery shortfall cannot be made up with time either."}`,
      response: "Lengthen the stay, choose a closer destination, or drop the sample point. Do not attempt the full loop." });
    if (v.sunlight_hours < tot.ops_h) hazards.push({ id: "dark", severity: "warn", affects: ["rover"], title: "Part of the traverse falls outside sunlight",
      reason: `The site gets ${v.sunlight_hours.toFixed(1)} h of sunlight in the stay, and operations need ${tot.ops_h.toFixed(1)} h.`, response: "Plan the night portion as a stationary hold or carry extra battery." });
  }

  // ---------- astronaut ----------
  const astroStops = [stops[2], stops[3], { ...stops[2] }];
  const astro = planLegs(terrain, astroStops, A.astronaut.max_slope_deg, A, blocked, "gentle");
  const aBlocked = astro.filter((l) => !l.ok); const aKm = astro.filter((l) => l.ok).reduce((s, l) => s + l.distance_m / 1000, 0);
  const aH = aKm / A.astronaut.walk_kmh + A.sample_h;
  for (const l of aBlocked) hazards.push({ id: "astro-slope", severity: "block", affects: ["astronaut"], title: `No safe walking route from ${l.from} to ${l.to}`,
    reason: `All paths exceed the ${A.astronaut.max_slope_deg.toFixed(1)}° walking limit${blocked ? " or cross the obstacle zone" : ""}.`, response: "Crew must not walk this leg. Move the sample point or collect it with the rover." });
  if (!aBlocked.length && (aKm > A.astronaut.max_eva_km || aH > A.astronaut.max_eva_h)) hazards.push({ id: "eva-range", severity: "block", affects: ["astronaut"], title: "Walking traverse exceeds EVA limits",
    reason: `Walking loop is ${aKm.toFixed(1)} km and ${aH.toFixed(1)} h, against limits of ${A.astronaut.max_eva_km} km and ${A.astronaut.max_eva_h} h.`,
    response: "Move the sample point closer to the destination, or split the EVA in two." });
  if (aH > v.earth_visible_hours) hazards.push({ id: "astro-comm", severity: "block", affects: ["astronaut"], title: "EVA longer than Earth-contact time",
    reason: `The EVA needs ${aH.toFixed(1)} h but Earth is visible for only ${v.earth_visible_hours.toFixed(1)} h in the stay.`, response: "Split the EVA or shorten it." });
  else if (blackout > 0) hazards.push({ id: "astro-blackout", severity: "info", affects: ["astronaut"], title: "Schedule the EVA inside an Earth-visible window",
    reason: `A blackout of up to ${blackout.toFixed(1)} h occurs during the stay${scenarios.blackout ? " (includes 30 h simulated)" : ""}. Crew must keep contact with Earth.`, response: "Start the EVA only when Earth is above the horizon. Window timing must come from the visibility service." });
  if (v.sunlight_hours < aH) hazards.push({ id: "astro-dark", severity: "block", affects: ["astronaut"], title: v.sunlight_hours <= 0 ? "No sunlight at this site on this date" : "Not enough sunlight for the EVA",
    reason: `EVA needs ${aH.toFixed(1)} h of light, the site has ${v.sunlight_hours.toFixed(1)} h in the whole stay.`,
    response: v.sunlight_hours <= 0 ? "Shortening the EVA does not help. Choose another landing date or a higher, sunlit site." : `Shorten the EVA to under ${v.sunlight_hours.toFixed(1)} h or split it across sunlit periods.` });

  // ---------- verdicts ----------
  const worst = (who) => { const hs = hazards.filter((h) => h.affects.includes(who)); return hs.some((h) => h.severity === "block") ? "nogo" : hs.some((h) => h.severity === "warn") ? "conditional" : "go"; };
  const verdicts = { rover: worst("rover"), astronaut: worst("astronaut") };
  const rank = { go: 0, conditional: 1, nogo: 2 };
  const overall = actors.map((a) => verdicts[a]).sort((p, q) => rank[q] - rank[p])[0] || "go";
  const order = { block: 0, warn: 1, info: 2 }; hazards.sort((p, q) => order[p.severity] - order[q.severity]);
  // timeline (relative hours from landing)
  const timeline = []; let t0 = 0.5; timeline.push({ label: "Rover deployment", start: 0, end: 0.5, actor: "rover" });
  rover.forEach((l, k) => { if (!l.ok) return; const h = l.distance_m / A.rover.speed_mps / 3600; timeline.push({ label: `Drive to ${l.to}`, start: t0, end: t0 + h, actor: "rover" }); t0 += h;
    if (k === 1) { timeline.push({ label: "Sample collection", start: t0, end: t0 + A.sample_h, actor: "rover" }); t0 += A.sample_h;
      if (tot.recharge_h && Number.isFinite(tot.recharge_h)) { timeline.push({ label: "Solar recharge", start: t0, end: t0 + tot.recharge_h, actor: "rover" }); t0 += tot.recharge_h; } } });
  return { assumptions: A, scenarios, obstacle, ridge, rover, astro, astroTotals: { km: aKm, h: aH }, totals: tot, hazards, verdicts, overall, timeline, blackout, sunFrac,
    duration: dur, actors, terrainOrigin: terrain.origin, terrainStatus: terrain.status, notes };
}

/** Move a stop to the nearest cell whose own slope and all 8 neighbours are under 70% of the limit
 *  (within 4 km). Returns the stop with snapped_m set, or the original stop if nothing qualifies. */
export function snapToTraversable(terrain, stop, limit, awayFrom = null, minAway = 500) {
  const p = project(stop.lat, stop.lon), c = terrain.cellOf(p.x, p.y), R = Math.ceil(4000 / terrain.cell);
  const away = awayFrom ? project(awayFrom.lat, awayFrom.lon) : null;
  const ok = (i, j) => {
    if (away) { const q = terrain.cellCenter(i, j); if (Math.hypot(q.x - away.x, q.y - away.y) < minAway) return false; }
    for (let dj = -1; dj <= 1; dj++) for (let di = -1; di <= 1; di++) { const a = i + di, b = j + dj;
      if (a < 0 || b < 0 || a >= terrain.cols || b >= terrain.rows || terrain.slope[b * terrain.cols + a] > 0.7 * limit) return false; }
    return true; };
  if (ok(c.i, c.j)) return { ...stop, snapped_m: 0 };
  let best = null;
  for (let j = c.j - R; j <= c.j + R; j++) for (let i = c.i - R; i <= c.i + R; i++) { if (!ok(i, j)) continue; const d = Math.hypot(i - c.i, j - c.j); if (!best || d < best.d) best = { i, j, d }; }
  if (!best) return { ...stop, snapped_m: null };
  const q = terrain.cellCenter(best.i, best.j), ll = unproject(q.x, q.y);
  return { ...stop, lat: ll.lat_deg, lon: ll.lon_deg, snapped_m: Math.hypot(q.x - p.x, q.y - p.y), from: { lat: stop.lat, lon: stop.lon } };
}

/** Default destination + sample point: nearest navigation-module site to the landing site inside coverage,
 *  sample point 1.5 km further along the same bearing (clamped inside coverage). */
export function defaultStops(terrain, landing, p3sites) {
  const L = project(landing.lat, landing.lon);
  // On real terrain (named features present): survey point 5 km toward the nearest named crater,
  // e.g. the edge of a permanently shadowed region. Person 3's demo sites only fit its synthetic terrain.
  const feats = (terrain.features || []).map((f) => ({ f, p: project(f.lat_deg, f.lon_deg) })).map((o) => ({ ...o, d: Math.hypot(o.p.x - L.x, o.p.y - L.y) }))
    .filter((o) => o.d > 2500).sort((a, b) => a.d - b.d);
  if (feats.length) {
    const t = feats[0], ux = (t.p.x - L.x) / t.d, uy = (t.p.y - L.y) / t.d, go = Math.min(5000, t.d - 1500);
    const clamp = (x, lo, hi) => Math.max(lo, Math.min(hi, x));
    const dx = clamp(L.x + ux * go, terrain.ox + 600, terrain.maxX - 600), dy = clamp(L.y + uy * go, terrain.oy + 600, terrain.maxY - 600);
    const sx = clamp(dx + ux * 700, terrain.ox + 600, terrain.maxX - 600), sy = clamp(dy + uy * 700, terrain.oy + 600, terrain.maxY - 600);
    const dst = unproject(dx, dy), smp = unproject(sx, sy), dep = unproject(L.x + ux * 150, L.y + uy * 150);
    return { deploy: { lat: dep.lat_deg, lon: dep.lon_deg, name: "Rover deployment" },
      destination: { lat: dst.lat_deg, lon: dst.lon_deg, name: `Survey point ${(go / 1000).toFixed(1)} km toward ${t.f.name}` },
      sample: { lat: smp.lat_deg, lon: smp.lon_deg, name: "Sample point" } };
  }
  const cands = p3sites.map((s) => ({ s, p: project(s.location.lat_deg, s.location.lon_deg) })).filter((c) => terrain.inCoverageXY(c.p.x, c.p.y))
    .map((c) => ({ ...c, d: Math.hypot(c.p.x - L.x, c.p.y - L.y) })).filter((c) => c.d > 3000).sort((a, b) => a.d - b.d);
  const dst = cands[0]; if (!dst) return null;
  const ux = (dst.p.x - L.x) / dst.d, uy = (dst.p.y - L.y) / dst.d; let sx = dst.p.x + ux * 1500, sy = dst.p.y + uy * 1500;
  sx = Math.max(terrain.ox + 600, Math.min(terrain.maxX - 600, sx)); sy = Math.max(terrain.oy + 600, Math.min(terrain.maxY - 600, sy));
  const smp = unproject(sx, sy); const dep = unproject(L.x + ux * 150, L.y + uy * 150);
  return {
    deploy: { lat: dep.lat_deg, lon: dep.lon_deg, name: "Rover deployment" },
    destination: { lat: dst.s.location.lat_deg, lon: dst.s.location.lon_deg, name: dst.s.name.replace(/^Mock /, "") },
    sample: { lat: smp.lat_deg, lon: smp.lon_deg, name: "Sample point" },
  };
}
