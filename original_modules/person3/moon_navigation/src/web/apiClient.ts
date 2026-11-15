import type { ApiErrorBody, Location, RouteOutput, Site } from "../shared/types";

const BASE = (import.meta as unknown as { env?: Record<string, string> }).env?.VITE_API_BASE ?? "/api/v1";

export class ApiClientError extends Error {
  constructor(
    public code: string,
    message: string,
    public details?: unknown,
  ) {
    super(message);
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      ...init,
      headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiClientError("NETWORK_ERROR", "Cannot reach the moon_navigation API. Is `npm start` running?");
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const e = (body as ApiErrorBody | null)?.error;
    throw new ApiClientError(e?.code ?? "HTTP_ERROR", e?.message ?? `HTTP ${res.status}`, e?.details);
  }
  return body as T;
}

export interface TerrainGridResponse {
  data_status: string;
  cols: number;
  rows: number;
  cell_size_m: number;
  origin_x_m: number;
  origin_y_m: number;
  elevation_m: number[];
  slope_deg: number[];
  terrain_source: { name: string; data_status: string };
}

export interface FrameInfo {
  frame: string;
  map_projection: { id: string; proj4: string };
  reference_sphere_radius_m: number;
}

export const api = {
  frame: () => call<FrameInfo>("/meta/frame"),
  sites: () => call<{ sites: Site[]; data_status: string; upstream: string; warnings: string[] }>("/sites"),
  grid: (step = 2) => call<TerrainGridResponse>(`/terrain/grid?step=${step}`),
  sample: (lat: number, lon: number) =>
    call<{ terrain: { elevation_m: number; slope_deg: number } }>(`/terrain/sample?lat_deg=${lat}&lon_deg=${lon}`),
  distance: (points: Array<Pick<Location, "lat_deg" | "lon_deg">>) =>
    call<{ distance_m: number; surface_distance_m: number; segment_distances_m: number[] }>("/distance", {
      method: "POST",
      body: JSON.stringify({ points }),
    }),
  routes: (start: Location, target: Location, maxSlopeDeg: number, algorithm: "astar" | "dijkstra") =>
    call<RouteOutput>("/routes", {
      method: "POST",
      body: JSON.stringify({
        start: { lat_deg: start.lat_deg, lon_deg: start.lon_deg },
        target: { lat_deg: target.lat_deg, lon_deg: target.lon_deg },
        constraints: { max_slope_deg: maxSlopeDeg },
        algorithm,
      }),
    }),
};
