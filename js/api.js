import { CONFIG } from "./config.js?v=7";

/** kind: "network" | "validation" (422) | "upstream" (502) | "http" | "nav" */
export class ApiError extends Error {
  constructor(kind, status, message, details) {
    super(message);
    this.kind = kind; this.status = status; this.details = details;
  }
}

function formatValidation(detail) {
  if (!Array.isArray(detail)) return String(detail ?? "Invalid request");
  return detail.map((d) => {
    const loc = (d.loc || []).filter((x) => x !== "body").join(".");
    return loc ? `${loc}: ${d.msg}` : d.msg;
  }).join("; ");
}

async function call(base, path, body, { signal, service = "planner" } = {}) {
  let res;
  try {
    res = await fetch(base + path, {
      method: body === undefined ? "GET" : "POST",
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch (e) {
    if (e.name === "AbortError") throw e;
    throw new ApiError("network", 0, service === "planner"
      ? `Cannot reach the mission planner at ${CONFIG.apiBase}. Start it with: python -m uvicorn api.main:app --port 8000`
      : `Cannot reach Moon navigation at ${CONFIG.navBase}. Start it with: pnpm start (in original_modules/person3/moon_navigation)`);
  }
  const data = await res.json().catch(() => null);
  if (res.ok) return data;
  if (service === "nav") {
    const e = data?.error;
    throw new ApiError("nav", res.status, e ? `${e.code}: ${e.message}` : `HTTP ${res.status}`, e?.details);
  }
  if (res.status === 422) throw new ApiError("validation", 422, formatValidation(data?.detail), data?.detail);
  if (res.status === 502) throw new ApiError("upstream", 502, data?.error?.message || "Upstream or planning error", data?.error);
  throw new ApiError("http", res.status, data?.error?.message || `HTTP ${res.status}`, data);
}

/* ---- Recorded mode (public site, no backend) ----
 * data/recorded/recordings.json holds real responses that the backend returned while running on NASA
 * LRO LOLA + JPL Horizons data, for the four preset missions. A request is answered only if it matches a
 * recorded request exactly; anything else says plainly that it needs the live backend. Nothing is computed
 * or invented in the browser. */
export const REPO_URL = "https://github.com/roaalhejaili/luna-nav-ai";
const LIVE_HINT = `This public site replays real runs recorded from the NASA-data backend for the four preset missions. To plan other settings live, download the project (${REPO_URL}) and double-click RUN.bat.`;
let recordings = null;
export async function recordedRuns() {
  if (!recordings) {
    const res = await fetch(new URL("../data/recorded/recordings.json", import.meta.url));
    if (!res.ok) throw new ApiError("network", 0, "The recorded NASA-data runs are missing from this site.");
    recordings = await res.json();
  }
  return recordings;
}
const canon = (v) => Array.isArray(v) ? `[${v.map(canon).join(",")}]`
  : v && typeof v === "object" ? `{${Object.keys(v).sort().map((k) => `${JSON.stringify(k)}:${canon(v[k])}`).join(",")}}`
  : JSON.stringify(v);
async function replay(kind, body) {
  const rec = await recordedRuns(), key = canon(body);
  const hit = (rec[kind] || []).find((x) => canon(x.body) === key);
  if (!hit) throw new ApiError("recorded", 0, `${kind === "replan" ? "Replanning" : "These mission settings"} need the live planner. ${LIVE_HINT}`);
  return structuredClone(hit.response);
}

/** Person 4 public API — contracts from API_CONTRACT.md / openapi.json */
export const planner = CONFIG.recorded ? {
  health: async () => ({ status: "ok", mode: "recorded" }),
  plan: (requirements) => replay("plan", requirements),
  replan: () => replay("replan", null),
  compare: (requirements) => replay("compare", { requirements }),
} : {
  health: () => call(CONFIG.apiBase, "/health"),
  plan: (requirements, opts) => call(CONFIG.apiBase, "/mission/plan", requirements, opts),
  replan: (previous, requirements, opts) => call(CONFIG.apiBase, "/mission/replan", { previous, requirements }, opts),
  compare: (requirements, opts) => call(CONFIG.apiBase, "/mission/compare", { requirements }, opts),
};

/** Person 3 moon_navigation API — contract from its API_CONTRACT.md (same calls as its apiClient.ts).
 *  In recorded mode it reports offline at once, so the app uses its bundled NASA LOLA terrain. */
const nav = (path, body) => CONFIG.recorded
  ? Promise.reject(new ApiError("nav", 0, "Public site: using the bundled NASA LOLA terrain."))
  : call(CONFIG.navBase, path, body, { service: "nav" });
export const moonNav = {
  health: () => nav("/health"),
  sites: () => nav("/sites"),
  grid: (step = 2) => nav(`/terrain/grid?step=${step}`),
  sample: (lat, lon) => nav(`/terrain/sample?lat_deg=${lat}&lon_deg=${lon}`),
  routes: (start, target, maxSlopeDeg, algorithm = "astar") => nav("/routes", {
    start: { lat_deg: start.lat_deg, lon_deg: start.lon_deg },
    target: { lat_deg: target.lat_deg, lon_deg: target.lon_deg },
    constraints: { max_slope_deg: maxSlopeDeg },
    algorithm,
  }),
};
