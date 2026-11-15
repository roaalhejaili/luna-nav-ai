import request from "supertest";
import { describe, expect, it } from "vitest";
import { createApp } from "../src/server/app";

const app = createApp();
const A = { lat_deg: -89.0, lon_deg: 0 };

async function sites() {
  const r = await request(app).get("/api/v1/sites");
  return r.body.sites as Array<{ site_id: string; location: { lat_deg: number; lon_deg: number } }>;
}

describe("GET /api/v1/health & meta", () => {
  it("reports module identity and MOCK data status", async () => {
    const r = await request(app).get("/api/v1/health");
    expect(r.status).toBe(200);
    expect(r.body).toMatchObject({ status: "ok", module: "moon_navigation", module_id: "03", data_status: "MOCK" });
    expect(r.headers["x-request-id"]).toBeTruthy();
    expect(new Date(r.body.generated_at_utc).toISOString()).toBe(r.body.generated_at_utc);
  });

  it("documents the lunar frame and projection", async () => {
    const r = await request(app).get("/api/v1/meta/frame");
    expect(r.body.frame).toBe("IAU_MOON_ME");
    expect(r.body.reference_sphere_radius_m).toBe(1737400);
    expect(r.body.map_projection.proj4).toContain("+proj=stere");
  });
});

describe("GET /api/v1/sites", () => {
  it("returns MOCK sites matching the Site Output shape", async () => {
    const r = await request(app).get("/api/v1/sites");
    expect(r.status).toBe(200);
    expect(r.body.data_status).toBe("MOCK");
    expect(r.body.upstream).toBe("mock");
    expect(r.body.sites.length).toBeGreaterThanOrEqual(3);
    for (const s of r.body.sites) {
      expect(s).toMatchObject({
        site_id: expect.any(String),
        location: { lat_deg: expect.any(Number), lon_deg: expect.any(Number), frame: "IAU_MOON_ME" },
        terrain: { slope_deg: expect.any(Number), elevation_m: expect.any(Number) },
        data_status: "MOCK",
      });
    }
  });

  it("uses Module 01 when it responds with a valid contract", async () => {
    const fake = (async () =>
      new Response(
        JSON.stringify({
          sites: [{ site_id: "S1", location: { lat_deg: -89.1, lon_deg: 5 }, data_status: "REAL" }],
        }),
        { status: 200 },
      )) as unknown as typeof fetch;
    const a = createApp({ sitesUpstreamUrl: "http://module01.test/sites", sitesFetch: fake });
    const r = await request(a).get("/api/v1/sites");
    expect(r.body.upstream).toBe("landing_site_analyzer");
    expect(r.body.sites[0].site_id).toBe("S1");
    expect(r.body.data_status).toBe("REAL");
  });

  it("falls back to MOCK when Module 01 is down", async () => {
    const down = (async () => {
      throw new Error("ECONNREFUSED");
    }) as unknown as typeof fetch;
    const a = createApp({ sitesUpstreamUrl: "http://module01.test/sites", sitesFetch: down });
    const r = await request(a).get("/api/v1/sites");
    expect(r.status).toBe(200);
    expect(r.body.upstream).toBe("mock");
    expect(r.body.data_status).toBe("MOCK");
    expect(r.body.warnings[0]).toMatch(/unreachable/);
  });

  it("falls back to MOCK when Module 01 breaks the contract", async () => {
    const bad = (async () => new Response(JSON.stringify({ nope: 1 }), { status: 200 })) as unknown as typeof fetch;
    const a = createApp({ sitesUpstreamUrl: "http://module01.test/sites", sitesFetch: bad });
    const r = await request(a).get("/api/v1/sites");
    expect(r.body.upstream).toBe("mock");
    expect(r.body.warnings[0]).toMatch(/contract/);
  });
});

describe("terrain endpoints", () => {
  it("samples terrain inside coverage", async () => {
    const r = await request(app).get("/api/v1/terrain/sample").query(A);
    expect(r.status).toBe(200);
    expect(r.body.terrain.elevation_m).toEqual(expect.any(Number));
    expect(r.body.data_status).toBe("MOCK");
  });

  it("422 OUT_OF_COVERAGE outside the fixture", async () => {
    const r = await request(app).get("/api/v1/terrain/sample").query({ lat_deg: -80, lon_deg: 0 });
    expect(r.status).toBe(422);
    expect(r.body.error.code).toBe("OUT_OF_COVERAGE");
    expect(r.body.request_id).toBeTruthy();
  });

  it("400 VALIDATION_ERROR on bad query", async () => {
    const r = await request(app).get("/api/v1/terrain/sample").query({ lat_deg: 120, lon_deg: 0 });
    expect(r.status).toBe(400);
    expect(r.body.error.code).toBe("VALIDATION_ERROR");
  });

  it("serves a downsampled grid", async () => {
    const r = await request(app).get("/api/v1/terrain/grid").query({ step: 10 });
    expect(r.status).toBe(200);
    expect(r.body.elevation_m).toHaveLength(r.body.cols * r.body.rows);
    expect(r.body.slope_deg).toHaveLength(r.body.cols * r.body.rows);
  });
});

describe("POST /api/v1/distance", () => {
  it("measures great-circle distance in meters", async () => {
    const r = await request(app)
      .post("/api/v1/distance")
      .send({ points: [{ lat_deg: -89, lon_deg: 0 }, { lat_deg: -90, lon_deg: 0 }] });
    expect(r.status).toBe(200);
    expect(r.body.distance_m).toBeCloseTo((1737400 * Math.PI) / 180, 0); // R * 1deg = ~30323.4 m
    expect(r.body.segment_distances_m).toHaveLength(1);
  });

  it("rejects fewer than two points", async () => {
    const r = await request(app).post("/api/v1/distance").send({ points: [A] });
    expect(r.status).toBe(400);
  });

  it("rejects malformed JSON", async () => {
    const r = await request(app).post("/api/v1/distance").set("content-type", "application/json").send("{bad");
    expect(r.status).toBe(400);
    expect(r.body.error.code).toBe("INVALID_JSON");
  });
});

describe("POST /api/v1/routes", () => {
  it("returns Route Output with three alternatives between mock sites", async () => {
    const s = await sites();
    const a = s.find((x) => x.site_id === "MOCK-SP-01")!;
    const c = s.find((x) => x.site_id === "MOCK-SP-03")!;
    const r = await request(app)
      .post("/api/v1/routes")
      .send({ start: a.location, target: c.location, constraints: { max_slope_deg: 15 } });
    expect(r.status).toBe(200);
    expect(r.body).toMatchObject({
      data_status: "MOCK",
      frame: "IAU_MOON_ME",
      operational_validity: "NOT_VALIDATED",
      algorithm: "astar",
    });
    expect(r.body.alternatives.map((x: { strategy: string }) => x.strategy)).toEqual(["shortest", "balanced", "gentle"]);
    const [shortest, , gentle] = r.body.alternatives;
    expect(shortest.distance_m).toBeLessThanOrEqual(gentle.distance_m + 1);
    expect(gentle.max_slope_deg).toBeLessThanOrEqual(shortest.max_slope_deg + 1e-9);
    expect(shortest.waypoints.length).toBeGreaterThanOrEqual(2);
    expect(shortest.waypoints[0].lat_deg).toBeCloseTo(a.location.lat_deg, 5);
    expect(r.body.disclaimers.length).toBeGreaterThan(0);
  });

  it("422 OUT_OF_COVERAGE", async () => {
    const r = await request(app)
      .post("/api/v1/routes")
      .send({ start: { lat_deg: -70, lon_deg: 0 }, target: A });
    expect(r.status).toBe(422);
    expect(r.body.error.code).toBe("OUT_OF_COVERAGE");
    expect(r.body.error.details.point).toBe("start");
  });

  it("422 NO_ROUTE_FOUND when the slope limit is impossible", async () => {
    const s = await sites();
    const r = await request(app)
      .post("/api/v1/routes")
      .send({ start: s[0].location, target: s[2].location, constraints: { max_slope_deg: 0.001 } });
    expect(r.status).toBe(422);
    expect(r.body.error.code).toBe("NO_ROUTE_FOUND");
  });

  it("400 on unknown fields and bad frame", async () => {
    const r1 = await request(app).post("/api/v1/routes").send({ start: A, target: A, bogus: 1 });
    expect(r1.status).toBe(400);
    const r2 = await request(app)
      .post("/api/v1/routes")
      .send({ start: { ...A, frame: "J2000" }, target: A });
    expect(r2.status).toBe(400);
    expect(r2.body.error.details[0].path).toBe("start.frame");
  });

  it("404 envelope for unknown routes", async () => {
    const r = await request(app).get("/api/v1/nope");
    expect(r.status).toBe(404);
    expect(r.body.error.code).toBe("NOT_FOUND");
  });
});
