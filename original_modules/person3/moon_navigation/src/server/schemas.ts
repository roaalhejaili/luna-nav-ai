import { z } from "zod";
import { LUNAR_FRAME } from "../shared/types.js";

export const LocationSchema = z
  .object({
    lat_deg: z.number().finite().min(-90).max(90),
    lon_deg: z.number().finite().min(-180).max(180),
    elevation_m: z.number().finite().nullable().optional(),
    frame: z.literal(LUNAR_FRAME).optional(),
  })
  .strict();

export const DistanceRequestSchema = z
  .object({
    points: z.array(LocationSchema).min(2).max(2000),
  })
  .strict();

export const RouteRequestSchema = z
  .object({
    start: LocationSchema,
    target: LocationSchema,
    constraints: z
      .object({
        max_slope_deg: z.number().finite().gt(0).max(45).default(15),
      })
      .strict()
      .default({ max_slope_deg: 15 }),
    algorithm: z.enum(["astar", "dijkstra"]).default("astar"),
    strategies: z
      .array(z.enum(["shortest", "balanced", "gentle"]))
      .min(1)
      .max(3)
      .default(["shortest", "balanced", "gentle"]),
  })
  .strict();

export const TerrainSampleQuerySchema = z.object({
  lat_deg: z.coerce.number().finite().min(-90).max(90),
  lon_deg: z.coerce.number().finite().min(-180).max(180),
});

export const TerrainGridQuerySchema = z.object({
  step: z.coerce.number().int().min(1).max(20).default(4),
});

// Lenient parser for Module 01 "Site Output" when pulled from upstream.
export const UpstreamSiteSchema = z.object({
  site_id: z.string().min(1),
  name: z.string().optional(),
  location: LocationSchema,
  terrain: z
    .object({
      elevation_m: z.number().nullable().optional(),
      slope_deg: z.number().nullable().optional(),
      roughness_m: z.number().nullable().optional(),
    })
    .partial()
    .optional(),
  reason: z.string().optional(),
  source: z.string().optional(),
  data_status: z.enum(["REAL", "MOCK", "PARTIAL", "UNAVAILABLE"]).optional(),
});
export const UpstreamSitesResponseSchema = z.object({
  sites: z.array(UpstreamSiteSchema),
});
