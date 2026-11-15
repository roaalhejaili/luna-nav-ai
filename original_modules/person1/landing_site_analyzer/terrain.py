"""Terrain data adapters and local terrain derivatives."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

MOON_RADIUS_M = 1_737_400.0
NASA_DATA_URL = "https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/data/lola_gdr/cylindrical/img/"


@dataclass
class TerrainGrid:
    elevations_m: np.ndarray
    pixels_per_degree: float
    source: str
    provider: str
    source_url: str | None
    product_id: str | None
    data_status: str
    real_data: bool
    fallback_reason: str | None = None
    north_latitude_center_deg: float = 89.5
    west_longitude_center_deg: float = 0.5
    # Optional polar stereographic support (e.g. NASA LOLA LDEM_75S_240M). Cylindrical grids keep the defaults.
    projection: str = "CYLINDRICAL"
    polar_scale_m: float | None = None
    polar_hemisphere: int = -1            # -1 south, +1 north
    polar_limit_latitude_deg: float | None = None

    @property
    def resolution_m(self) -> float:
        if self.projection == "POLAR" and self.polar_scale_m:
            return self.polar_scale_m
        return 2 * math.pi * MOON_RADIUS_M / (360 * self.pixels_per_degree)


def _pds_value(label: str, name: str, default: str | None = None) -> str | None:
    match = re.search(rf"^\s*{re.escape(name)}\s*=\s*([^\r\n/]+)", label, re.MULTILINE | re.IGNORECASE)
    return match.group(1).strip().strip('"') if match else default


def load_pds_img(img_path: str | Path, label_path: str | Path | None = None) -> TerrainGrid:
    """Load an uncompressed PDS3 16-bit cylindrical LOLA image with its detached label."""
    img_path = Path(img_path)
    label_path = Path(label_path) if label_path else img_path.with_suffix(".lbl")
    if not img_path.is_file() or not label_path.is_file():
        raise FileNotFoundError("Both PDS IMG and detached LBL files are required")
    label = label_path.read_text(encoding="ascii", errors="replace")
    lines, columns = int(_pds_value(label, "LINES", "0")), int(_pds_value(label, "LINE_SAMPLES", "0"))
    bits = int(_pds_value(label, "SAMPLE_BITS", "0"))
    sample_type = (_pds_value(label, "SAMPLE_TYPE", "") or "").upper()
    scale = float(_pds_value(label, "SCALING_FACTOR", "1"))
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("PDS SCALING_FACTOR must be a finite positive number")
    if lines <= 0 or columns <= 0 or bits != 16:
        raise ValueError("Unsupported or incomplete PDS image label; expected 16-bit image dimensions")
    if "INTEGER" not in sample_type:
        raise ValueError(f"Unsupported PDS SAMPLE_TYPE: {sample_type}")
    endian = ">" if sample_type.startswith("MSB") else "<"
    dtype = np.dtype(f"{endian}i2")
    expected_bytes = lines * columns * dtype.itemsize
    if img_path.stat().st_size != expected_bytes:
        raise ValueError(f"PDS image byte length mismatch: expected {expected_bytes}, got {img_path.stat().st_size}")
    offset = _pds_value(label, "^IMAGE")
    if offset and offset.startswith("("):
        record = int(re.search(r",\s*(\d+)", offset).group(1))
        record_bytes = int(_pds_value(label, "RECORD_BYTES", "1"))
        byte_offset = max(0, (record - 1) * record_bytes)
    else:
        byte_offset = 0
    raw = np.memmap(img_path, dtype=dtype, mode="r", offset=byte_offset, shape=(lines, columns))
    raw_values = np.asarray(raw, dtype=np.float32)
    missing = _pds_value(label, "MISSING_CONSTANT") or _pds_value(label, "MISSING_VALUE")
    if missing is not None:
        raw_values[raw_values == float(missing)] = np.nan
    values = raw_values * scale
    projection = (_pds_value(label, "MAP_PROJECTION_TYPE", "SIMPLE CYLINDRICAL") or "").upper()
    coord = (_pds_value(label, "COORDINATE_SYSTEM_NAME", "MEAN EARTH/POLAR AXIS") or "").upper()
    if "POLAR STEREOGRAPHIC" in projection and "MEAN EARTH" in coord:
        center_lat = float((_pds_value(label, "CENTER_LATITUDE", "-90") or "-90").split()[0])
        scale_m = float((_pds_value(label, "MAP_SCALE", "240") or "240").split()[0])
        limit = float((_pds_value(label, "MAXIMUM_LATITUDE" if center_lat < 0 else "MINIMUM_LATITUDE", "0") or "0").split()[0])
        if abs(abs(center_lat) - 90) > 1e-6 or lines != columns:
            raise ValueError("Polar stereographic grid must be square and centred on a pole")
        ppd = float((_pds_value(label, "MAP_RESOLUTION", "1") or "1").split()[0])
        return TerrainGrid(values, ppd, f"LRO LOLA {img_path.name}", "NASA PDS Geosciences Node",
                           NASA_DATA_URL.replace("/cylindrical/", "/polar/") + img_path.name.lower(),
                           img_path.stem.upper(), "REAL", True, None, center_lat, 0.0, "POLAR", scale_m,
                           -1 if center_lat < 0 else 1, limit)
    if "CYLINDRICAL" not in projection or "MEAN EARTH" not in coord:
        raise ValueError("Only LOLA mean-Earth, simple-cylindrical products are supported")
    ppd = float(_pds_value(label, "MAP_RESOLUTION", "16").split()[0])
    if not math.isfinite(ppd) or ppd <= 0:
        raise ValueError("PDS MAP_RESOLUTION must be a finite positive number")
    line_offset = float((_pds_value(label, "LINE_PROJECTION_OFFSET", str((lines - 1) / 2)) or "0").split()[0])
    sample_offset = float((_pds_value(label, "SAMPLE_PROJECTION_OFFSET", str((columns - 1) / 2)) or "0").split()[0])
    center_lat = float((_pds_value(label, "CENTER_LATITUDE", "0") or "0").split()[0])
    center_lon = float((_pds_value(label, "CENTER_LONGITUDE", "180") or "180").split()[0])
    # PDS projection offsets are expressed in 1-based pixel coordinates.
    first_lat = center_lat + line_offset / ppd
    first_lon = center_lon - sample_offset / ppd
    return TerrainGrid(values, ppd, f"LRO LOLA {img_path.name}", "NASA PDS Geosciences Node", NASA_DATA_URL + img_path.name.lower(),
                       img_path.stem.upper(), "REAL", True, None, first_lat, first_lon % 360.0)


def mock_grid(fallback_reason: str | None = None) -> TerrainGrid:
    """Build a tiny deterministic synthetic grid for demo/tests; never represents NASA data."""
    rows, cols, ppd = 180, 360, 1.0
    lat = (89.5 - np.arange(rows, dtype=np.float32))[:, None]
    lon = (0.5 + np.arange(cols, dtype=np.float32))[None, :]
    elevations = (850 * np.sin(np.deg2rad(lat * 1.7)) + 260 * np.cos(np.deg2rad(lon * 3.0))
                  + 45 * np.sin(np.deg2rad(lat * 8 + lon * 2))).astype(np.float32)
    return TerrainGrid(elevations, ppd, "Deterministic synthetic test surface", "LUNA NAV AI local fixture", None,
                       "synthetic-grid-v1", "MOCK", False, fallback_reason, 89.5, 0.5)


def polar_pixel(grid: TerrainGrid, latitude_deg: float, longitude_deg: float) -> tuple[float, float]:
    """(column, row), 0-based, for a polar stereographic grid (PDS DSMAP_POLAR forward equations,
    orientation as verified by Person 2 against Shackleton, Shoemaker and Cabeus)."""
    n = grid.elevations_m.shape[0]; c = n / 2 - 0.5
    rho = 2 * MOON_RADIUS_M * math.tan(math.radians(90 - abs(latitude_deg)) / 2)
    lon = math.radians(longitude_deg)
    x, y = rho * math.sin(lon), rho * math.cos(lon) * (1 if grid.polar_hemisphere < 0 else -1)
    return x / grid.polar_scale_m + c, c - y / grid.polar_scale_m


def polar_latlon(grid: TerrainGrid, col: float, row: float) -> tuple[float, float]:
    n = grid.elevations_m.shape[0]; c = n / 2 - 0.5
    x, y = (col - c) * grid.polar_scale_m, (c - row) * grid.polar_scale_m * (1 if grid.polar_hemisphere < 0 else -1)
    lat = grid.polar_hemisphere * (90 - math.degrees(2 * math.atan(math.hypot(x, y) / (2 * MOON_RADIUS_M))))
    return lat, math.degrees(math.atan2(x, y))


def _sample_polar(grid: TerrainGrid, latitude_deg: float, longitude_deg: float) -> tuple[float, float, float] | None:
    if (latitude_deg < 0) != (grid.polar_hemisphere < 0):
        return None
    if grid.polar_limit_latitude_deg is not None and abs(latitude_deg) < abs(grid.polar_limit_latitude_deg):
        return None
    cf, rf = polar_pixel(grid, latitude_deg, longitude_deg)
    col, row = int(round(cf)), int(round(rf)); n = grid.elevations_m.shape[0]
    if col < 1 or row < 1 or col > n - 2 or row > n - 2:
        return None
    patch = np.asarray(grid.elevations_m[row - 1:row + 2, col - 1:col + 2], dtype=float)
    if not np.isfinite(patch).all():
        return None
    s = grid.polar_scale_m
    dzdx = (patch[1, 2] - patch[1, 0]) / (2 * s); dzdy = (patch[0, 1] - patch[2, 1]) / (2 * s)
    return float(patch[1, 1]), float(math.degrees(math.atan(math.hypot(dzdx, dzdy)))), float(np.std(patch))


def polar_local_highs(grid: TerrainGrid, bounds, max_slope_deg: float, count: int,
                      window_m: float = 1000.0, spacing_m: float = 3000.0) -> list[tuple[float, float]]:
    """Candidate points on local high ground inside the region: cells that are the highest within
    window_m, have 3x3 slope <= max_slope_deg, ordered by elevation, at least spacing_m apart.
    Near the poles, higher ground stays sunlit longer; illumination itself is computed by Person 2."""
    n = grid.elevations_m.shape[0]; c = n / 2 - 0.5; s = grid.polar_scale_m
    outer = max(abs(bounds.min_latitude_deg), abs(bounds.max_latitude_deg)) if grid.polar_hemisphere < 0 else 0
    inner_lat = min(abs(bounds.min_latitude_deg), abs(bounds.max_latitude_deg))
    r_max = 2 * MOON_RADIUS_M * math.tan(math.radians(90 - inner_lat) / 2)
    k = min(int(c) - 2, int(r_max / s) + 2)
    r0, r1, c0, c1 = int(c) - k, int(c) + k + 1, int(c) - k, int(c) + k + 1
    E = np.asarray(grid.elevations_m[r0:r1, c0:c1], dtype=np.float64)
    gy, gx = np.gradient(E, s); slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    w = max(1, int(round(window_m / s)))
    pad = np.pad(E, w, mode="edge"); lmax = E.copy()
    for di in range(-w, w + 1):
        for dj in range(-w, w + 1):
            lmax = np.maximum(lmax, pad[w + di:w + di + E.shape[0], w + dj:w + dj + E.shape[1]])
    rows, cols = np.nonzero((E >= lmax) & (slope <= max_slope_deg) & np.isfinite(E))
    order = np.argsort(-E[rows, cols]); picked: list[tuple[float, float]] = []; pts: list[tuple[float, float]] = []
    for idx in order:
        rr, cc = rows[idx] + r0, cols[idx] + c0
        lat, lon = polar_latlon(grid, cc, rr)
        if not (bounds.min_latitude_deg <= lat <= bounds.max_latitude_deg):
            continue
        lon_span = (bounds.max_longitude_deg - bounds.min_longitude_deg) % 360.0 or 360.0
        if lon_span < 360.0 and (lon - bounds.min_longitude_deg) % 360.0 > lon_span:
            continue
        x, y = (cc - c) * s, (c - rr) * s
        if any(math.hypot(x - px, y - py) < spacing_m for px, py in pts):
            continue
        pts.append((x, y)); picked.append((lat, lon))
        if len(picked) >= count:
            break
    return picked


def sample_terrain(grid: TerrainGrid, latitude_deg: float, longitude_deg: float) -> tuple[float, float, float] | None:
    """Nearest-cell elevation plus 3x3 local planar slope and elevation std-dev roughness."""
    if grid.projection == "POLAR":
        return _sample_polar(grid, latitude_deg, longitude_deg)
    lat = float(latitude_deg)
    lon360 = float(longitude_deg) % 360.0
    row_float = (grid.north_latitude_center_deg - lat) * grid.pixels_per_degree
    row = int(round(row_float))
    if row_float < -0.5 or row_float > grid.elevations_m.shape[0] - 0.5:
        return None
    row = min(max(row, 0), grid.elevations_m.shape[0] - 1)
    if grid.elevations_m.shape[1] / grid.pixels_per_degree >= 360.0:
        col_float = ((lon360 - grid.west_longitude_center_deg) % 360.0) * grid.pixels_per_degree
        col = int(round(col_float)) % grid.elevations_m.shape[1]
    else:
        lon_delta = (lon360 - grid.west_longitude_center_deg) % 360.0
        col_float = lon_delta * grid.pixels_per_degree
        if col_float > grid.elevations_m.shape[1] - 0.5:
            return None
        col = int(round(col_float))
    r0, r1 = max(0, row - 1), min(grid.elevations_m.shape[0], row + 2)
    c = np.array([(col - 1) % grid.elevations_m.shape[1], col, (col + 1) % grid.elevations_m.shape[1]])
    patch = np.asarray(grid.elevations_m[r0:r1][:, c], dtype=float)
    finite = np.isfinite(patch)
    if not finite[patch.shape[0] // 2, 1]:
        return None
    if finite.sum() < 5:
        return None
    # Approximate local gradient in the N/S and E/W directions; grid is in degrees.
    row_values = np.nanmean(np.where(finite, patch, np.nan), axis=1)
    col_values = np.nanmean(np.where(finite, patch, np.nan), axis=0)
    dy_m = max(1.0, grid.resolution_m)
    dx_m = max(1.0, dy_m * abs(math.cos(math.radians(lat))))
    north_south = (row_values[0] - row_values[-1]) / (dy_m * max(1, len(row_values) - 1)) if len(row_values) > 1 else 0.0
    east_west = (col_values[-1] - col_values[0]) / (2 * dx_m)
    slope = math.degrees(math.atan(math.hypot(north_south, east_west)))
    roughness = float(np.nanstd(np.where(finite, patch, np.nan)))
    return float(patch[patch.shape[0] // 2, 1]), float(slope), roughness
