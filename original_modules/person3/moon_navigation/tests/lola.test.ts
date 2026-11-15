import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import request from "supertest";
import { loadLolaGrid } from "../src/server/lolaTerrain.js";
import { sampleTerrain } from "../src/server/terrain.js";
import { createApp } from "../src/server/app.js";

// Real NASA LRO LOLA LDEM_75S_240M. Shared with Person 2 (fetch with scripts/get_nasa_lola.py).
const DEM =
  process.env.LUNA_P3_LOLA_PATH ??
  resolve(__dirname, "../../../person2/member2/data/lola/ldem_75s_240m.img");
const has = existsSync(DEM);

describe.skipIf(!has)("NASA LOLA terrain (LDEM_75S_240M)", () => {
  const grid = has ? loadLolaGrid(DEM, 80_000, 1) : (undefined as never);

  it("loads a REAL 240 m crop centred on the pole", () => {
    expect(grid.source.data_status).toBe("REAL");
    expect(grid.cellSizeM).toBe(240);
    expect(grid.cols).toBe(grid.rows);
    expect(grid.cols * grid.cellSizeM).toBeGreaterThan(159_000);
  });

  it("matches a direct read of the NASA file at a known pixel (-88.458, 292.156E -> 1575.0 m)", () => {
    const s = sampleTerrain(grid, -88.458, 292.156 - 360)!;
    expect(s).not.toBeNull();
    expect(Math.abs(s.elevation_m - 1575.0)).toBeLessThan(25);
  });

  it("shows Shackleton crater as a deep depression (map is not mirrored)", () => {
    const floor = sampleTerrain(grid, -89.67, 129.78)!.elevation_m; // Shackleton centre
    const rim = sampleTerrain(grid, -89.9, 0)!.elevation_m; // rim near the pole
    expect(rim - floor).toBeGreaterThan(2_500);
  });

  it("routes over real terrain and labels them REAL", async () => {
    const app = createApp({ grid });
    const health = await request(app).get("/api/v1/health");
    expect(health.body.data_status).toBe("REAL");
    const res = await request(app)
      .post("/api/v1/routes")
      .send({ start: { lat_deg: -89.3, lon_deg: 30 }, target: { lat_deg: -89.0, lon_deg: 60 }, constraints: { max_slope_deg: 20 } });
    expect([200, 422]).toContain(res.status);
    if (res.status === 200) {
      expect(res.body.data_status).toMatch(/REAL|PARTIAL/);
      expect(res.body.terrain_source.name).toContain("LOLA");
    }
  });
});
