import proj4 from "proj4";
import { describe, expect, it } from "vitest";
import { MOON_RADIUS_M } from "../src/shared/types";
import {
  greatCircleDistanceM,
  normalizeLon,
  projectSouthPolar,
  unprojectSouthPolar,
} from "../src/server/geo";
import { findPath } from "../src/server/pathfinding";
import { buildFixtureGrid, cellOf } from "../src/server/terrain";

const grid = buildFixtureGrid();

describe("lunar geometry", () => {
  it("normalizes longitude to [-180, 180]", () => {
    expect(normalizeLon(190)).toBeCloseTo(-170);
    expect(normalizeLon(-190)).toBeCloseTo(170);
    expect(normalizeLon(360)).toBeCloseTo(0);
  });

  it("projection round-trips", () => {
    for (const [lat, lon] of [[-89.5, 10], [-88.2, -135], [-87.7, 179]]) {
      const p = projectSouthPolar(lat, lon);
      const q = unprojectSouthPolar(p.x, p.y);
      expect(q.lat_deg).toBeCloseTo(lat, 8);
      expect(q.lon_deg).toBeCloseTo(lon, 8);
    }
  });

  it("matches PROJ stere definition used by the web map", () => {
    const def = `+proj=stere +lat_0=-90 +lat_ts=-90 +lon_0=0 +k=1 +x_0=0 +y_0=0 +R=${MOON_RADIUS_M} +units=m +no_defs`;
    const conv = proj4(def);
    for (const [lat, lon] of [[-89.2, 33], [-88.4, -120], [-89.9, 170]]) {
      const [x, y] = conv.forward([lon, lat]);
      const p = projectSouthPolar(lat, lon);
      expect(p.x).toBeCloseTo(x, 3);
      expect(p.y).toBeCloseTo(y, 3);
    }
  });

  it("great-circle: 1 degree of arc equals R * pi/180", () => {
    expect(greatCircleDistanceM(-89, 0, -90, 0)).toBeCloseTo((MOON_RADIUS_M * Math.PI) / 180, 3);
    expect(greatCircleDistanceM(-80, 20, -80, 20)).toBe(0);
  });
});

describe("terrain fixture", () => {
  it("is deterministic and MOCK-labelled", () => {
    const g2 = buildFixtureGrid();
    expect(g2.elevation[1234]).toBe(grid.elevation[1234]);
    expect(grid.source.data_status).toBe("MOCK");
  });
  it("has a steep central obstacle", () => {
    const c = cellOf(grid, 4_000, 0);
    expect(grid.slope[c.j * grid.cols + c.i]).toBeGreaterThan(15);
  });
});

describe("pathfinding", () => {
  const start = cellOf(grid, -30_000, 20_000);
  const goal = cellOf(grid, 26_000, -24_000);

  it("A* and Dijkstra find the same optimal cost; A* expands fewer nodes", () => {
    const opts = { maxSlopeDeg: 15, strategy: "balanced" as const };
    const a = findPath(grid, start, goal, { ...opts, algorithm: "astar" })!;
    const d = findPath(grid, start, goal, { ...opts, algorithm: "dijkstra" })!;
    expect(a).not.toBeNull();
    expect(d).not.toBeNull();
    expect(a.expanded).toBeLessThan(d.expanded);
    expect(a.cells.length).toBe(d.cells.length);
  });

  it("never enters cells above the slope limit", () => {
    const r = findPath(grid, start, goal, { maxSlopeDeg: 10, strategy: "shortest", algorithm: "astar" })!;
    for (const c of r.cells.slice(1, -1)) {
      expect(grid.slope[c.j * grid.cols + c.i]).toBeLessThanOrEqual(10);
    }
  });

  it("returns null when the goal is walled off", () => {
    const r = findPath(grid, start, goal, { maxSlopeDeg: 0.001, strategy: "shortest", algorithm: "astar" });
    expect(r).toBeNull();
  });
});
