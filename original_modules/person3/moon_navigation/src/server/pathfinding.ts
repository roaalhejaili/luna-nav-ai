import type { RouteAlgorithm, RouteStrategy } from "../shared/types.js";
import { cellCenter, type TerrainGrid } from "./terrain.js";

/** Slope-penalty weight per strategy: cost = step * (1 + w * (slope/limit)^2). */
export const STRATEGY_WEIGHT: Record<RouteStrategy, number> = {
  shortest: 0,
  balanced: 4,
  gentle: 24,
};

class MinHeap {
  private keys: number[] = [];
  private vals: number[] = [];
  get size() {
    return this.keys.length;
  }
  push(key: number, val: number) {
    this.keys.push(key);
    this.vals.push(val);
    let i = this.keys.length - 1;
    while (i > 0) {
      const p = (i - 1) >> 1;
      if (this.keys[p] <= this.keys[i]) break;
      this.swap(i, p);
      i = p;
    }
  }
  pop(): number {
    const top = this.vals[0];
    const lastK = this.keys.pop()!;
    const lastV = this.vals.pop()!;
    if (this.keys.length > 0) {
      this.keys[0] = lastK;
      this.vals[0] = lastV;
      let i = 0;
      const n = this.keys.length;
      for (;;) {
        const l = 2 * i + 1;
        const r = l + 1;
        let m = i;
        if (l < n && this.keys[l] < this.keys[m]) m = l;
        if (r < n && this.keys[r] < this.keys[m]) m = r;
        if (m === i) break;
        this.swap(i, m);
        i = m;
      }
    }
    return top;
  }
  private swap(a: number, b: number) {
    [this.keys[a], this.keys[b]] = [this.keys[b], this.keys[a]];
    [this.vals[a], this.vals[b]] = [this.vals[b], this.vals[a]];
  }
}

const NEIGHBORS: Array<[number, number, number]> = [
  [1, 0, 1],
  [-1, 0, 1],
  [0, 1, 1],
  [0, -1, 1],
  [1, 1, Math.SQRT2],
  [1, -1, Math.SQRT2],
  [-1, 1, Math.SQRT2],
  [-1, -1, Math.SQRT2],
];

export interface PathResult {
  /** Cell indices (i, j) from start to goal */
  cells: Array<{ i: number; j: number }>;
  expanded: number;
}

export interface FindPathOptions {
  maxSlopeDeg: number;
  strategy: RouteStrategy;
  algorithm: RouteAlgorithm;
}

/**
 * Grid path search over 8-connected cells.
 * - Cells with slope > maxSlopeDeg are hard-blocked (start/goal cells are exempt).
 * - algorithm "astar" uses a Euclidean heuristic (admissible: cost multiplier >= 1);
 *   "dijkstra" uses h = 0. Both return the same optimal cost.
 */
export function findPath(
  grid: TerrainGrid,
  start: { i: number; j: number },
  goal: { i: number; j: number },
  opts: FindPathOptions,
): PathResult | null {
  const { cols, rows, cellSizeM } = grid;
  const w = STRATEGY_WEIGHT[opts.strategy];
  const limit = opts.maxSlopeDeg;
  const startIdx = start.j * cols + start.i;
  const goalIdx = goal.j * cols + goal.i;

  const g = new Float64Array(cols * rows).fill(Infinity);
  const parent = new Int32Array(cols * rows).fill(-1);
  const closed = new Uint8Array(cols * rows);
  const heap = new MinHeap();

  const h = (idx: number) => {
    if (opts.algorithm === "dijkstra") return 0;
    const i = idx % cols;
    const j = (idx / cols) | 0;
    return Math.hypot(i - goal.i, j - goal.j) * cellSizeM;
  };

  g[startIdx] = 0;
  heap.push(h(startIdx), startIdx);
  let expanded = 0;

  while (heap.size > 0) {
    const cur = heap.pop();
    if (closed[cur]) continue;
    closed[cur] = 1;
    expanded++;
    if (cur === goalIdx) break;
    const ci = cur % cols;
    const cj = (cur / cols) | 0;
    for (const [di, dj, mult] of NEIGHBORS) {
      const ni = ci + di;
      const nj = cj + dj;
      if (ni < 0 || nj < 0 || ni >= cols || nj >= rows) continue;
      const nIdx = nj * cols + ni;
      if (closed[nIdx]) continue;
      const nSlope = grid.slope[nIdx];
      if (nIdx !== goalIdx && nSlope > limit) continue;
      // avoid cutting corners through blocked cells on diagonals
      if (di !== 0 && dj !== 0) {
        const a = grid.slope[cj * cols + ni];
        const b = grid.slope[nj * cols + ci];
        if (a > limit || b > limit) continue;
      }
      const avgSlope = (grid.slope[cur] + nSlope) / 2;
      const step = mult * cellSizeM * (1 + w * (avgSlope / limit) ** 2);
      const ng = g[cur] + step;
      if (ng < g[nIdx]) {
        g[nIdx] = ng;
        parent[nIdx] = cur;
        heap.push(ng + h(nIdx), nIdx);
      }
    }
  }

  if (!Number.isFinite(g[goalIdx])) return null;

  const cells: Array<{ i: number; j: number }> = [];
  for (let idx = goalIdx; idx !== -1; idx = parent[idx]) {
    cells.push({ i: idx % cols, j: (idx / cols) | 0 });
    if (idx === startIdx) break;
  }
  cells.reverse();
  return { cells, expanded };
}

/** Drop intermediate points that lie on a straight grid direction. */
export function simplifyCells(cells: Array<{ i: number; j: number }>) {
  if (cells.length <= 2) return cells;
  const out = [cells[0]];
  for (let k = 1; k < cells.length - 1; k++) {
    const a = cells[k - 1];
    const b = cells[k];
    const c = cells[k + 1];
    if (b.i - a.i !== c.i - b.i || b.j - a.j !== c.j - b.j) out.push(b);
  }
  out.push(cells[cells.length - 1]);
  return out;
}

export { cellCenter };
