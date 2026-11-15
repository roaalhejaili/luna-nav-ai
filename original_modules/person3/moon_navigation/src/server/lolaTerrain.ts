import { readFileSync, openSync, readSync, closeSync, existsSync } from "node:fs";
import type { TerrainGrid } from "./terrain.js";

/**
 * Real NASA terrain: LRO LOLA LDEM_75S_240M (PDS Geosciences Node), the 240 m south-polar DEM
 * that the NASA Space Apps "Lunar Landing Site Navigator" challenge points to (LOLA / Quickmap / Moon Trek).
 *
 * The product uses the same south-polar stereographic projection as this module
 * (+proj=stere +lat_0=-90 +lon_0=0 +R=1737400), so a crop maps directly onto TerrainGrid:
 *   LOLA sample (column) = SAMPLE_PROJECTION_OFFSET + x / MAP_SCALE   (0-based pixel centre)
 *   LOLA line   (row)    = LINE_PROJECTION_OFFSET   - y / MAP_SCALE
 * Heights: DN (int16, little-endian) * SCALING_FACTOR metres above the 1737.4 km reference sphere.
 */

interface LolaLabel {
  lines: number;
  samples: number;
  scale: number;
  lineOffset: number;
  sampleOffset: number;
  scaling: number;
  centerLat: number;
  radiusM: number;
}

function num(label: string, key: string): number {
  const m = label.match(new RegExp(`^\\s*${key}\\s*=\\s*(-?[0-9.]+)`, "m"));
  if (!m) throw new Error(`LOLA label is missing ${key}`);
  return Number(m[1]);
}

export function parseLolaLabel(text: string): LolaLabel {
  const radiusKm = num(text, "A_AXIS_RADIUS");
  const label: LolaLabel = {
    lines: num(text, "LINES"),
    samples: num(text, "LINE_SAMPLES"),
    scale: num(text, "MAP_SCALE"),
    lineOffset: num(text, "LINE_PROJECTION_OFFSET"),
    sampleOffset: num(text, "SAMPLE_PROJECTION_OFFSET"),
    scaling: num(text, "SCALING_FACTOR"),
    centerLat: num(text, "CENTER_LATITUDE"),
    radiusM: radiusKm * 1000,
  };
  if (label.centerLat !== -90) throw new Error("Expected a south-polar LOLA product (CENTER_LATITUDE = -90)");
  if (num(text, "SAMPLE_BITS") !== 16) throw new Error("Expected 16-bit LOLA samples");
  if (!/SAMPLE_TYPE\s*=\s*LSB_INTEGER/.test(text)) throw new Error("Expected LSB_INTEGER LOLA samples");
  return label;
}

/**
 * Crop the DEM to a square of +/- halfExtentM around the pole.
 * stride = 1 keeps native 240 m pixels; stride = 2 block-averages to 480 m (faster routing).
 */
export function loadLolaGrid(imgPath: string, halfExtentM = 80_000, stride = 1): TerrainGrid {
  const lblPath = imgPath.replace(/\.img$/i, ".lbl");
  if (!existsSync(imgPath) || !existsSync(lblPath)) throw new Error(`LOLA DEM or label not found: ${imgPath}`);
  const label = parseLolaLabel(readFileSync(lblPath, "latin1"));
  if (Math.abs(label.radiusM - 1_737_400) > 1) throw new Error(`Unexpected LOLA reference radius ${label.radiusM}`);
  const cell = label.scale * stride;
  const half = Math.floor(halfExtentM / cell);
  const n = 2 * half + 1;
  const elevation = new Float32Array(n * n);

  // Read only the rows we need (the full file is 29 MB).
  const fd = openSync(imgPath, "r");
  const rowBuf = Buffer.alloc(label.samples * 2);
  try {
    for (let j = 0; j < n; j++) {
      const y = (j - half) * cell; // grid row j -> projected y (origin at bottom)
      for (let i = 0; i < n; i++) elevation[j * n + i] = 0;
      let count = 0;
      for (let dy = 0; dy < stride; dy++) {
        const row = Math.round(label.lineOffset - (y + (dy - (stride - 1) / 2) * label.scale) / label.scale);
        if (row < 0 || row >= label.lines) throw new Error("LOLA crop exceeds DEM coverage");
        readSync(fd, rowBuf, 0, rowBuf.length, row * label.samples * 2);
        for (let i = 0; i < n; i++) {
          const x = (i - half) * cell;
          for (let dx = 0; dx < stride; dx++) {
            const col = Math.round(label.sampleOffset + (x + (dx - (stride - 1) / 2) * label.scale) / label.scale);
            if (col < 0 || col >= label.samples) throw new Error("LOLA crop exceeds DEM coverage");
            elevation[j * n + i] += rowBuf.readInt16LE(col * 2) * label.scaling;
          }
        }
        count += stride;
      }
      for (let i = 0; i < n; i++) elevation[j * n + i] /= count;
    }
  } finally {
    closeSync(fd);
  }

  const slope = new Float32Array(n * n);
  for (let j = 0; j < n; j++) {
    for (let i = 0; i < n; i++) {
      const im = Math.max(i - 1, 0), ip = Math.min(i + 1, n - 1);
      const jm = Math.max(j - 1, 0), jp = Math.min(j + 1, n - 1);
      const dzdx = (elevation[j * n + ip] - elevation[j * n + im]) / ((ip - im) * cell);
      const dzdy = (elevation[jp * n + i] - elevation[jm * n + i]) / ((jp - jm) * cell);
      slope[j * n + i] = (Math.atan(Math.hypot(dzdx, dzdy)) * 180) / Math.PI;
    }
  }

  return {
    cols: n,
    rows: n,
    cellSizeM: cell,
    originX: -half * cell,
    originY: -half * cell,
    elevation,
    slope,
    source: {
      name: "NASA LRO LOLA LDEM_75S_240M (PDS Geosciences Node)",
      version: "LDEM_75S_240M",
      resolution_m: cell,
      data_status: "REAL",
    },
  };
}
