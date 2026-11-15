import { LUNAR_FRAME, type DataStatus, type Site } from "../shared/types.js";
import { unprojectSouthPolar } from "./geo.js";
import { sampleTerrain, type TerrainGrid } from "./terrain.js";
import { UpstreamSitesResponseSchema } from "./schemas.js";

/** Fixed demo sites (projected meters in the synthetic fixture). Module 03 never needs Module 01 to run. */
const MOCK_POSITIONS: Array<{ id: string; name: string; x: number; y: number; reason: string }> = [
  { id: "MOCK-SP-01", name: "Mock Site A (NW plateau)", x: -30_000, y: 20_000, reason: "Low slope on a broad rise (fixture)." },
  { id: "MOCK-SP-02", name: "Mock Site B (NE ridge)", x: 22_000, y: 26_000, reason: "Moderate slope, ridge-top (fixture)." },
  { id: "MOCK-SP-03", name: "Mock Site C (SE basin)", x: 26_000, y: -24_000, reason: "Flat basin floor (fixture)." },
  { id: "MOCK-SP-04", name: "Mock Site D (SW basin)", x: -24_000, y: -26_000, reason: "Flat basin floor (fixture)." },
];

export function mockSites(grid: TerrainGrid): Site[] {
  return MOCK_POSITIONS.map((p) => {
    const ll = unprojectSouthPolar(p.x, p.y);
    const t = sampleTerrain(grid, ll.lat_deg, ll.lon_deg)!;
    return {
      site_id: p.id,
      name: p.name,
      location: {
        lat_deg: round6(ll.lat_deg),
        lon_deg: round6(ll.lon_deg),
        elevation_m: Math.round(t.elevation_m * 10) / 10,
        frame: LUNAR_FRAME,
      },
      terrain: {
        elevation_m: Math.round(t.elevation_m * 10) / 10,
        slope_deg: Math.round(t.slope_deg * 100) / 100,
        roughness_m: null,
      },
      reason: p.reason,
      source: "moon_navigation mock fixture",
      data_status: "MOCK" as const,
    };
  });
}

const round6 = (v: number) => Math.round(v * 1e6) / 1e6;

export interface SitesResult {
  sites: Site[];
  data_status: DataStatus;
  warnings: string[];
  upstream: "landing_site_analyzer" | "mock";
}

/**
 * Returns candidate sites. If LANDING_SITES_URL is set, tries Module 01 (GET <url>) with a short
 * timeout and validates the response; on any failure falls back to MOCK sites and says so.
 */
export async function getSites(
  grid: TerrainGrid,
  opts: { upstreamUrl?: string; timeoutMs?: number; fetchImpl?: typeof fetch } = {},
): Promise<SitesResult> {
  const url = opts.upstreamUrl ?? process.env.LANDING_SITES_URL;
  const fallback = (warning?: string): SitesResult => ({
    sites: mockSites(grid),
    data_status: "MOCK",
    warnings: warning ? [warning] : [],
    upstream: "mock",
  });
  if (!url) return fallback();

  const f = opts.fetchImpl ?? fetch;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), opts.timeoutMs ?? 2000);
  try {
    const res = await f(url, { signal: ctrl.signal, headers: { accept: "application/json" } });
    if (!res.ok) return fallback(`Module 01 responded HTTP ${res.status}; using MOCK sites.`);
    const parsed = UpstreamSitesResponseSchema.safeParse(await res.json());
    if (!parsed.success) return fallback("Module 01 response did not match the Site Output contract; using MOCK sites.");

    const sites: Site[] = [];
    const warnings: string[] = [];
    for (const s of parsed.data.sites) {
      const sampled = sampleTerrain(grid, s.location.lat_deg, s.location.lon_deg);
      if (!sampled) {
        warnings.push(`Site ${s.site_id} is outside this module's terrain coverage; kept without terrain sample.`);
      }
      sites.push({
        site_id: s.site_id,
        name: s.name ?? s.site_id,
        location: {
          lat_deg: s.location.lat_deg,
          lon_deg: s.location.lon_deg,
          elevation_m: s.location.elevation_m ?? sampled?.elevation_m ?? null,
          frame: LUNAR_FRAME,
        },
        terrain: {
          elevation_m: s.terrain?.elevation_m ?? null,
          slope_deg: s.terrain?.slope_deg ?? null,
          roughness_m: s.terrain?.roughness_m ?? null,
        },
        reason: s.reason ?? "",
        source: s.source ?? "landing_site_analyzer",
        data_status: s.data_status ?? "REAL",
      });
    }
    const allReal = sites.length > 0 && sites.every((s) => s.data_status === "REAL");
    return {
      sites,
      data_status: allReal && warnings.length === 0 ? "REAL" : "PARTIAL",
      warnings,
      upstream: "landing_site_analyzer",
    };
  } catch (e) {
    return fallback(`Module 01 unreachable (${(e as Error).name}); using MOCK sites.`);
  } finally {
    clearTimeout(timer);
  }
}
