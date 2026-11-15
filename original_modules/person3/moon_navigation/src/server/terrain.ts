import type { TerrainSource } from "../shared/types.js";
import { projectSouthPolar, unprojectSouthPolar } from "./geo.js";

/**
 * Deterministic SYNTHETIC terrain fixture near the lunar south pole.
 * It is NOT NASA data. Every response derived from it is labelled data_status = "MOCK".
 * Replace `buildFixtureGrid()` with a loader for a real DEM (LOLA / Moon Trek) later;
 * the TerrainGrid interface below is all the rest of the module depends on.
 */

export interface TerrainGrid {
  cols: number;
  rows: number;
  cellSizeM: number;
  /** Projected coordinate (m) of the center of cell (0,0) */
  originX: number;
  originY: number;
  elevation: Float32Array; // meters, row-major (row = y index)
  slope: Float32Array; // degrees
  source: TerrainSource;
}

interface Feature {
  x: number;
  y: number;
  sigma: number;
  amp: number;
}

// amp < 0 => depression (crater), amp > 0 => rise. The steep crater at the center is an obstacle.
const FEATURES: Feature[] = [
  { x: 0, y: 0, sigma: 4_000, amp: -2_600 }, // steep crater (obstacle, slopes > 15 deg)
  { x: -26_000, y: 18_000, sigma: 9_000, amp: 700 },
  { x: 24_000, y: -22_000, sigma: 8_000, amp: -500 },
  { x: 20_000, y: 24_000, sigma: 6_000, amp: 450 },
  { x: -22_000, y: -24_000, sigma: 7_000, amp: -350 },
];

export function fixtureElevation(x: number, y: number): number {
  let z = 1_200; // base level (m)
  for (const f of FEATURES) {
    const d2 = (x - f.x) ** 2 + (y - f.y) ** 2;
    z += f.amp * Math.exp(-d2 / (2 * f.sigma * f.sigma));
  }
  // gentle deterministic undulation
  z += 25 * Math.sin(x / 3_100) * Math.cos(y / 2_700);
  return z;
}

export const FIXTURE_HALF_EXTENT_M = 50_000;
export const FIXTURE_CELL_M = 500;

export function buildFixtureGrid(
  halfExtentM = FIXTURE_HALF_EXTENT_M,
  cellSizeM = FIXTURE_CELL_M,
): TerrainGrid {
  const n = Math.round((2 * halfExtentM) / cellSizeM) + 1;
  const originX = -halfExtentM;
  const originY = -halfExtentM;
  const elevation = new Float32Array(n * n);
  for (let j = 0; j < n; j++) {
    for (let i = 0; i < n; i++) {
      elevation[j * n + i] = fixtureElevation(originX + i * cellSizeM, originY + j * cellSizeM);
    }
  }
  const slope = new Float32Array(n * n);
  for (let j = 0; j < n; j++) {
    for (let i = 0; i < n; i++) {
      const im = Math.max(i - 1, 0);
      const ip = Math.min(i + 1, n - 1);
      const jm = Math.max(j - 1, 0);
      const jp = Math.min(j + 1, n - 1);
      const dzdx = (elevation[j * n + ip] - elevation[j * n + im]) / ((ip - im) * cellSizeM);
      const dzdy = (elevation[jp * n + i] - elevation[jm * n + i]) / ((jp - jm) * cellSizeM);
      slope[j * n + i] = (Math.atan(Math.hypot(dzdx, dzdy)) * 180) / Math.PI;
    }
  }
  return {
    cols: n,
    rows: n,
    cellSizeM,
    originX,
    originY,
    elevation,
    slope,
    source: {
      name: "SYNTHETIC south-pole fixture (not NASA data)",
      version: "fixture-1.0.0",
      resolution_m: cellSizeM,
      data_status: "MOCK",
    },
  };
}

export function inCoverage(grid: TerrainGrid, x: number, y: number): boolean {
  const maxX = grid.originX + (grid.cols - 1) * grid.cellSizeM;
  const maxY = grid.originY + (grid.rows - 1) * grid.cellSizeM;
  return x >= grid.originX && x <= maxX && y >= grid.originY && y <= maxY;
}

export function coverageBounds(grid: TerrainGrid) {
  const maxX = grid.originX + (grid.cols - 1) * grid.cellSizeM;
  const maxY = grid.originY + (grid.rows - 1) * grid.cellSizeM;
  return {
    projected_extent_m: [grid.originX, grid.originY, maxX, maxY] as [number, number, number, number],
    corners: [
      unprojectSouthPolar(grid.originX, grid.originY),
      unprojectSouthPolar(maxX, grid.originY),
      unprojectSouthPolar(maxX, maxY),
      unprojectSouthPolar(grid.originX, maxY),
    ],
    max_latitude_deg: unprojectSouthPolar(maxX, 0).lat_deg,
  };
}

export function cellOf(grid: TerrainGrid, x: number, y: number): { i: number; j: number } {
  const i = Math.min(grid.cols - 1, Math.max(0, Math.round((x - grid.originX) / grid.cellSizeM)));
  const j = Math.min(grid.rows - 1, Math.max(0, Math.round((y - grid.originY) / grid.cellSizeM)));
  return { i, j };
}

export function cellCenter(grid: TerrainGrid, i: number, j: number): { x: number; y: number } {
  return { x: grid.originX + i * grid.cellSizeM, y: grid.originY + j * grid.cellSizeM };
}

/** Bilinear interpolation of a grid field at projected (x, y). */
function bilinear(grid: TerrainGrid, field: Float32Array, x: number, y: number): number {
  const fx = (x - grid.originX) / grid.cellSizeM;
  const fy = (y - grid.originY) / grid.cellSizeM;
  const i0 = Math.min(grid.cols - 2, Math.max(0, Math.floor(fx)));
  const j0 = Math.min(grid.rows - 2, Math.max(0, Math.floor(fy)));
  const tx = Math.min(1, Math.max(0, fx - i0));
  const ty = Math.min(1, Math.max(0, fy - j0));
  const v = (i: number, j: number) => field[j * grid.cols + i];
  return (
    v(i0, j0) * (1 - tx) * (1 - ty) +
    v(i0 + 1, j0) * tx * (1 - ty) +
    v(i0, j0 + 1) * (1 - tx) * ty +
    v(i0 + 1, j0 + 1) * tx * ty
  );
}

export function sampleTerrain(grid: TerrainGrid, latDeg: number, lonDeg: number) {
  const { x, y } = projectSouthPolar(latDeg, lonDeg);
  if (!inCoverage(grid, x, y)) return null;
  return {
    elevation_m: bilinear(grid, grid.elevation, x, y),
    slope_deg: bilinear(grid, grid.slope, x, y),
    x_m: x,
    y_m: y,
  };
}
