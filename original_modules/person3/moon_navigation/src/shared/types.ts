/**
 * LUNA NAV AI - shared contract types (Module 03: moon_navigation).
 * Units: angles in degrees, distances/elevations in meters, timestamps ISO-8601 UTC.
 * Frame: IAU_MOON_ME (Moon Mean Earth / Polar Axis), selenographic lat/lon,
 * longitude east-positive in [-180, 180], reference sphere R = 1 737 400 m.
 */

export const API_VERSION = "1.0.0";
export const LUNAR_FRAME = "IAU_MOON_ME" as const;
export const MOON_RADIUS_M = 1_737_400;
export const PROJECTION_ID = "LUNA_SP_STEREO" as const;

export type DataStatus = "REAL" | "MOCK" | "PARTIAL" | "UNAVAILABLE";

export interface Location {
  lat_deg: number;
  lon_deg: number;
  /** Meters above the 1 737 400 m reference sphere; null when unknown. */
  elevation_m: number | null;
  frame: typeof LUNAR_FRAME;
}

export interface TerrainProps {
  elevation_m: number | null;
  slope_deg: number | null;
  roughness_m: number | null;
}

/** Site Output shape (Module 01 -> Module 03). */
export interface Site {
  site_id: string;
  name: string;
  location: Location;
  terrain: TerrainProps;
  reason: string;
  source: string;
  data_status: DataStatus;
}

export type RouteStrategy = "shortest" | "balanced" | "gentle";
export type RouteAlgorithm = "astar" | "dijkstra";

export interface RouteAlternative {
  alt_id: string;
  strategy: RouteStrategy;
  distance_m: number;
  straight_line_distance_m: number;
  max_slope_deg: number;
  mean_slope_deg: number;
  elevation_gain_m: number;
  elevation_loss_m: number;
  waypoints: Location[];
  warnings: string[];
}

export interface RouteOutput {
  route_id: string;
  request_id: string;
  generated_at_utc: string;
  data_status: DataStatus;
  frame: typeof LUNAR_FRAME;
  algorithm: RouteAlgorithm;
  start: Location;
  target: Location;
  max_slope_limit_deg: number;
  alternatives: RouteAlternative[];
  terrain_source: TerrainSource;
  operational_validity: "NOT_VALIDATED";
  disclaimers: string[];
}

export interface TerrainSource {
  name: string;
  version: string;
  resolution_m: number;
  data_status: DataStatus;
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details?: unknown;
  };
  request_id: string;
  timestamp_utc: string;
}
