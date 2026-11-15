import { randomUUID } from "node:crypto";
import cors from "cors";
import express, { type NextFunction, type Request, type Response } from "express";
import { ZodError, type ZodTypeAny, type z } from "zod";
import {
  API_VERSION,
  LUNAR_FRAME,
  MOON_RADIUS_M,
  PROJECTION_ID,
} from "../shared/types.js";
import { ApiError, errorBody } from "./errors.js";
import { greatCircleDistanceM, projectSouthPolar } from "./geo.js";
import { computeRoutes, pathDistanceM, toLocation } from "./routeService.js";
import {
  DistanceRequestSchema,
  RouteRequestSchema,
  TerrainGridQuerySchema,
  TerrainSampleQuerySchema,
} from "./schemas.js";
import { getSites } from "./sitesProvider.js";
import {
  buildFixtureGrid,
  coverageBounds,
  inCoverage,
  sampleTerrain,
  type TerrainGrid,
} from "./terrain.js";

declare module "express-serve-static-core" {
  interface Request {
    requestId: string;
  }
}

function parse<T extends ZodTypeAny>(schema: T, value: unknown): z.infer<T> {
  const r = schema.safeParse(value);
  if (!r.success) {
    throw new ApiError(
      400,
      "VALIDATION_ERROR",
      "Request validation failed.",
      r.error.issues.map((i) => ({ path: i.path.join("."), message: i.message })),
    );
  }
  return r.data;
}

export interface AppOptions {
  grid?: TerrainGrid;
  sitesUpstreamUrl?: string;
  sitesTimeoutMs?: number;
  sitesFetch?: typeof fetch;
}

export function createApp(options: AppOptions = {}) {
  const grid = options.grid ?? buildFixtureGrid();
  const app = express();
  app.use(cors());
  app.use(express.json({ limit: "1mb" }));
  app.use((req, res, next) => {
    req.requestId = (req.header("x-request-id") ?? randomUUID()).slice(0, 64);
    res.setHeader("x-request-id", req.requestId);
    next();
  });

  const v1 = express.Router();
  const envelope = (req: Request, data_status: string, payload: object) => ({
    request_id: req.requestId,
    generated_at_utc: new Date().toISOString(),
    data_status,
    ...payload,
  });

  v1.get("/health", (req, res) => {
    res.json(
      envelope(req, grid.source.data_status, {
        status: "ok",
        module: "moon_navigation",
        module_id: "03",
        api_version: API_VERSION,
        terrain_source: grid.source,
        dependencies: {
          landing_site_analyzer: process.env.LANDING_SITES_URL ? "configured" : "not_configured (using mock sites)",
        },
      }),
    );
  });

  v1.get("/meta/frame", (req, res) => {
    res.json(
      envelope(req, "REAL", {
        frame: LUNAR_FRAME,
        description:
          "IAU Moon Mean Earth / Polar Axis (ME) selenographic frame. Latitude +north, longitude +east in [-180,180].",
        reference_sphere_radius_m: MOON_RADIUS_M,
        units: { angle: "deg", distance: "m", elevation: "m above reference sphere", time: "ISO-8601 UTC" },
        map_projection: {
          id: PROJECTION_ID,
          proj4: `+proj=stere +lat_0=-90 +lat_ts=-90 +lon_0=0 +k=1 +x_0=0 +y_0=0 +R=${MOON_RADIUS_M} +units=m +no_defs`,
          note: "South-polar stereographic on the lunar sphere. Planar x/y are for display only; distances use great-circle math.",
        },
      }),
    );
  });

  v1.get("/terrain/coverage", (req, res) => {
    res.json(envelope(req, grid.source.data_status, { terrain_source: grid.source, ...coverageBounds(grid), cell_size_m: grid.cellSizeM }));
  });

  v1.get("/terrain/sample", (req, res) => {
    const q = parse(TerrainSampleQuerySchema, req.query);
    const s = sampleTerrain(grid, q.lat_deg, q.lon_deg);
    if (!s) {
      throw new ApiError(422, "OUT_OF_COVERAGE", "Point is outside the supported terrain coverage.", {
        coverage: coverageBounds(grid),
      });
    }
    res.json(
      envelope(req, grid.source.data_status, {
        location: toLocation(grid, q.lat_deg, q.lon_deg),
        terrain: {
          elevation_m: Math.round(s.elevation_m * 10) / 10,
          slope_deg: Math.round(s.slope_deg * 100) / 100,
          roughness_m: null,
        },
        terrain_source: grid.source,
      }),
    );
  });

  // Downsampled grid for terrain-layer rendering (elevation + slope, row-major).
  v1.get("/terrain/grid", (req, res) => {
    const { step } = parse(TerrainGridQuerySchema, req.query);
    const cols: number[] = [];
    for (let i = 0; i < grid.cols; i += step) cols.push(i);
    const rowsIdx: number[] = [];
    for (let j = 0; j < grid.rows; j += step) rowsIdx.push(j);
    const elevation: number[] = [];
    const slope: number[] = [];
    for (const j of rowsIdx) {
      for (const i of cols) {
        elevation.push(Math.round(grid.elevation[j * grid.cols + i] * 10) / 10);
        slope.push(Math.round(grid.slope[j * grid.cols + i] * 100) / 100);
      }
    }
    res.json(
      envelope(req, grid.source.data_status, {
        terrain_source: grid.source,
        cols: cols.length,
        rows: rowsIdx.length,
        cell_size_m: grid.cellSizeM * step,
        origin_x_m: grid.originX,
        origin_y_m: grid.originY,
        row_order: "south_to_north_by_projected_y",
        elevation_m: elevation,
        slope_deg: slope,
      }),
    );
  });

  v1.get("/sites", async (req, res) => {
    const r = await getSites(grid, {
      upstreamUrl: options.sitesUpstreamUrl,
      timeoutMs: options.sitesTimeoutMs,
      fetchImpl: options.sitesFetch,
    });
    res.json(envelope(req, r.data_status, { sites: r.sites, upstream: r.upstream, warnings: r.warnings }));
  });

  v1.post("/distance", (req, res) => {
    const body = parse(DistanceRequestSchema, req.body);
    const pts = body.points.map((p) => {
      const s = sampleTerrain(grid, p.lat_deg, p.lon_deg);
      return {
        lat_deg: p.lat_deg,
        lon_deg: p.lon_deg,
        elevation_m: p.elevation_m ?? (s ? s.elevation_m : null),
      };
    });
    const segments = [];
    let flat = 0;
    for (let k = 1; k < pts.length; k++) {
      const d = greatCircleDistanceM(pts[k - 1].lat_deg, pts[k - 1].lon_deg, pts[k].lat_deg, pts[k].lon_deg);
      segments.push(Math.round(d * 10) / 10);
      flat += d;
    }
    const allInCoverage = pts.every((p) => {
      const pr = projectSouthPolar(p.lat_deg, p.lon_deg);
      return inCoverage(grid, pr.x, pr.y);
    });
    res.json(
      envelope(req, allInCoverage ? grid.source.data_status : "PARTIAL", {
        method: "great_circle_haversine",
        reference_sphere_radius_m: MOON_RADIUS_M,
        distance_m: Math.round(flat * 10) / 10,
        surface_distance_m: Math.round(pathDistanceM(pts) * 10) / 10,
        segment_distances_m: segments,
        notes: allInCoverage ? [] : ["Some points are outside terrain coverage; surface_distance_m ignores elevation there."],
      }),
    );
  });

  v1.post("/routes", (req, res) => {
    const body = parse(RouteRequestSchema, req.body);
    const out = computeRoutes(grid, body, req.requestId);
    res.json(out);
  });

  app.use("/api/v1", v1);

  app.use((req, _res, next) => next(new ApiError(404, "NOT_FOUND", `No route for ${req.method} ${req.path}`)));

  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  app.use((err: unknown, req: Request, res: Response, _next: NextFunction) => {
    if (err instanceof ApiError) {
      res.status(err.status).json(errorBody(err.code, err.message, req.requestId, err.details));
    } else if (err instanceof ZodError) {
      res.status(400).json(errorBody("VALIDATION_ERROR", "Request validation failed.", req.requestId, err.issues));
    } else if ((err as { type?: string })?.type === "entity.parse.failed") {
      res.status(400).json(errorBody("INVALID_JSON", "Request body is not valid JSON.", req.requestId));
    } else {
      console.error(err);
      res.status(500).json(errorBody("INTERNAL_ERROR", "Unexpected server error.", req.requestId));
    }
  });

  return app;
}
