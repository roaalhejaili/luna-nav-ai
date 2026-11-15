import { randomUUID } from "node:crypto";
import {
  LUNAR_FRAME,
  type DataStatus,
  type Location,
  type RouteAlgorithm,
  type RouteAlternative,
  type RouteOutput,
  type RouteStrategy,
} from "../shared/types.js";
import { ApiError } from "./errors.js";
import { greatCircleDistanceM, projectSouthPolar, unprojectSouthPolar } from "./geo.js";
import { findPath, simplifyCells } from "./pathfinding.js";
import {
  cellCenter,
  cellOf,
  coverageBounds,
  inCoverage,
  sampleTerrain,
  type TerrainGrid,
} from "./terrain.js";

export const DISCLAIMERS = [
  "Routes are exploratory terrain-only estimates. Operational validity is NOT validated.",
  "No hazard, rock-field, illumination or communication analysis is included in this module.",
  "A candidate site or route is not an approved landing site or traverse.",
];

export function toLocation(
  grid: TerrainGrid,
  latDeg: number,
  lonDeg: number,
): Location {
  const s = sampleTerrain(grid, latDeg, lonDeg);
  return {
    lat_deg: round(latDeg, 6),
    lon_deg: round(lonDeg, 6),
    elevation_m: s ? round(s.elevation_m, 1) : null,
    frame: LUNAR_FRAME,
  };
}

const round = (v: number, d: number) => Math.round(v * 10 ** d) / 10 ** d;

export function pathDistanceM(points: Array<{ lat_deg: number; lon_deg: number; elevation_m: number | null }>) {
  let total = 0;
  for (let k = 1; k < points.length; k++) {
    const a = points[k - 1];
    const b = points[k];
    const flat = greatCircleDistanceM(a.lat_deg, a.lon_deg, b.lat_deg, b.lon_deg);
    const dz = a.elevation_m != null && b.elevation_m != null ? b.elevation_m - a.elevation_m : 0;
    total += Math.hypot(flat, dz);
  }
  return total;
}

export interface RouteRequest {
  start: { lat_deg: number; lon_deg: number };
  target: { lat_deg: number; lon_deg: number };
  constraints: { max_slope_deg: number };
  algorithm: RouteAlgorithm;
  strategies: RouteStrategy[];
}

export function computeRoutes(grid: TerrainGrid, req: RouteRequest, requestId: string): RouteOutput {
  const s = projectSouthPolar(req.start.lat_deg, req.start.lon_deg);
  const t = projectSouthPolar(req.target.lat_deg, req.target.lon_deg);
  const bounds = coverageBounds(grid);
  for (const [label, p, src] of [
    ["start", s, req.start],
    ["target", t, req.target],
  ] as const) {
    if (!inCoverage(grid, p.x, p.y)) {
      throw new ApiError(
        422,
        "OUT_OF_COVERAGE",
        `${label} point (${src.lat_deg}, ${src.lon_deg}) is outside the supported terrain coverage.`,
        { point: label, coverage: bounds },
      );
    }
  }
  const startCell = cellOf(grid, s.x, s.y);
  const goalCell = cellOf(grid, t.x, t.y);
  const limit = req.constraints.max_slope_deg;

  const alternatives: RouteAlternative[] = [];
  const failed: RouteStrategy[] = [];
  for (const strategy of req.strategies) {
    const res = findPath(grid, startCell, goalCell, {
      maxSlopeDeg: limit,
      strategy,
      algorithm: req.algorithm,
    });
    if (!res) {
      failed.push(strategy);
      continue;
    }
    const slopes = res.cells.map((c) => grid.slope[c.j * grid.cols + c.i]);
    const elevs = res.cells.map((c) => grid.elevation[c.j * grid.cols + c.i]);
    let gain = 0;
    let loss = 0;
    for (let k = 1; k < elevs.length; k++) {
      const d = elevs[k] - elevs[k - 1];
      if (d > 0) gain += d;
      else loss -= d;
    }
    const simplified = simplifyCells(res.cells);
    const waypoints: Location[] = simplified.map((c, idx) => {
      if (idx === 0) return toLocation(grid, req.start.lat_deg, req.start.lon_deg);
      if (idx === simplified.length - 1) return toLocation(grid, req.target.lat_deg, req.target.lon_deg);
      const { x, y } = cellCenter(grid, c.i, c.j);
      const ll = unprojectSouthPolar(x, y);
      return toLocation(grid, ll.lat_deg, ll.lon_deg);
    });
    const maxSlope = Math.max(...slopes);
    const warnings: string[] = [`Terrain is ${grid.source.data_status}: ${grid.source.name}.`];
    if (maxSlope > 0.8 * limit) warnings.push(`Route reaches ${round(maxSlope, 1)} deg, close to the ${limit} deg limit.`);
    if (slopes[0] > limit) warnings.push("Start cell slope exceeds the limit.");
    if (slopes[slopes.length - 1] > limit) warnings.push("Target cell slope exceeds the limit.");
    alternatives.push({
      alt_id: `${strategy}-${alternatives.length + 1}`,
      strategy,
      distance_m: round(pathDistanceM(waypoints), 1),
      straight_line_distance_m: round(
        greatCircleDistanceM(req.start.lat_deg, req.start.lon_deg, req.target.lat_deg, req.target.lon_deg),
        1,
      ),
      max_slope_deg: round(maxSlope, 2),
      mean_slope_deg: round(slopes.reduce((a, b) => a + b, 0) / slopes.length, 2),
      elevation_gain_m: round(gain, 1),
      elevation_loss_m: round(loss, 1),
      waypoints,
      warnings,
    });
  }

  if (alternatives.length === 0) {
    throw new ApiError(
      422,
      "NO_ROUTE_FOUND",
      `No route satisfies max_slope_deg=${limit} between the given points.`,
      { failed_strategies: failed, hint: "Increase constraints.max_slope_deg or choose other points." },
    );
  }

  const status: DataStatus = grid.source.data_status;
  return {
    route_id: randomUUID(),
    request_id: requestId,
    generated_at_utc: new Date().toISOString(),
    data_status: failed.length > 0 && status === "REAL" ? "PARTIAL" : status,
    frame: LUNAR_FRAME,
    algorithm: req.algorithm,
    start: toLocation(grid, req.start.lat_deg, req.start.lon_deg),
    target: toLocation(grid, req.target.lat_deg, req.target.lon_deg),
    max_slope_limit_deg: limit,
    alternatives,
    terrain_source: grid.source,
    operational_validity: "NOT_VALIDATED",
    disclaimers: failed.length
      ? [...DISCLAIMERS, `No feasible route for strategies: ${failed.join(", ")}.`]
      : DISCLAIMERS,
  };
}
