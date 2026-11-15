"""Convert NASA LRO LOLA LDEM_75S_240M into the terrain grid the frontend reads
(frontend/data/lola_south_pole.json), keeping the original 240 m pixels.

    .venv\\Scripts\\python.exe scripts\\build_lola_terrain.py [--half-km 80]

Input : original_modules/person2/member2/data/lola/ldem_75s_240m.img (+ .lbl), from get_nasa_lola.py
Output: same shape as Person 3 GET /terrain/grid (cols, rows, cell_size_m, origin_x_m, origin_y_m,
        elevation_m row-major, rows south->north by projected y), on Person 3's projection:
        south-polar stereographic, R = 1737.4 km, lon 0 toward +y, lon 90E toward +x.
Pixel geometry follows the PDS catalog DSMAP_POLAR.CAT forward equations (as verified by
Person 2 against Shackleton, Shoemaker and Cabeus):  X = (I - N/2 - 0.5)*scale,  Y = -(J - N/2 - 0.5)*scale.
Heights: DN * 0.5 m above the 1737.4 km sphere. Slope is computed by the frontend from these heights
(same central-difference formula as Person 3).
"""
import argparse, json, re, datetime
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
LOLA = ROOT / "original_modules" / "person2" / "member2" / "data" / "lola"
OUT = ROOT / "frontend" / "data" / "lola_south_pole.json"
R = 1737400.0
# IAU-named features (USGS Gazetteer of Planetary Nomenclature centres). Shackleton, Shoemaker and the ridge are also
# checked in Person 2 tests; this script prints each feature height so orientation can be confirmed.
FEATURES = [
    {"name": "Shackleton crater", "lat_deg": -89.67, "lon_deg": 129.78},
    {"name": "Shoemaker crater", "lat_deg": -88.14, "lon_deg": 44.91},
    {"name": "Connecting ridge (sunlit)", "lat_deg": -89.45, "lon_deg": -137.3, "kind": "ridge"},
    {"name": "de Gerlache crater", "lat_deg": -88.5, "lon_deg": -87.1},
    {"name": "Haworth crater", "lat_deg": -87.45, "lon_deg": -5.17},
]

def label_value(text, key):
    m = re.search(rf"^\s*{key}\s*=\s*\"?([-+0-9.A-Za-z_:]+)", text, re.M)
    if not m: raise SystemExit(f"PDS label missing {key}")
    return m.group(1)

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--half-km", type=float, default=80.0); ap.add_argument("--lola-dir", default=str(LOLA))
    ap.add_argument("--out", default=str(OUT)); a = ap.parse_args()
    d = Path(a.lola_dir); img, lbl = d / "ldem_75s_240m.img", d / "ldem_75s_240m.lbl"
    if not img.exists(): raise SystemExit(f"Missing {img}. Run scripts/get_nasa_lola.py first.")
    text = lbl.read_text(encoding="latin-1")
    n = int(label_value(text, "LINES")); scale = float(label_value(text, "MAP_SCALE")); sf = float(label_value(text, "SCALING_FACTOR"))
    assert label_value(text, "SAMPLE_TYPE") == "LSB_INTEGER" and int(label_value(text, "SAMPLE_BITS")) == 16
    assert float(label_value(text, "CENTER_LATITUDE")) == -90 and float(label_value(text, "A_AXIS_RADIUS")) == 1737.4
    if img.stat().st_size != n * n * 2: raise SystemExit(f"{img.name} has the wrong size; re-run get_nasa_lola.py")
    dem = np.memmap(img, dtype="<i2", mode="r", shape=(n, n))
    c0 = n / 2 - 0.5                      # 0-based index of the projection centre (pixel edges at the pole)
    k = int(np.floor(a.half_km * 1000 / scale))
    i0, i1 = int(np.ceil(c0 - k)), int(np.floor(c0 + k))   # columns (samples), x = (i - c0) * scale
    j0, j1 = i0, i1                                        # lines,  y = (c0 - j) * scale
    block = dem[j0:j1 + 1, i0:i1 + 1].astype(np.float32) * sf
    block = block[::-1, :]                                 # rows south->north by projected y
    rows, cols = block.shape
    origin_x = (i0 - c0) * scale; origin_y = (c0 - j1) * scale
    # sanity: report known features (height vs mirrored longitude)
    def h_at(lat, lon):
        rho = 2 * R * np.tan(np.radians(lat + 90) / 2); x, y = rho * np.sin(np.radians(lon)), rho * np.cos(np.radians(lon))
        ii, jj = int(round(x / scale + c0)), int(round(c0 - y / scale)); return float(dem[jj, ii]) * sf
    checks = []
    for f in FEATURES:
        h, m = h_at(f["lat_deg"], f["lon_deg"]), h_at(f["lat_deg"], -f["lon_deg"])
        checks.append(f"{f['name']:28s} height {h:8.0f} m   mirrored-longitude {m:8.0f} m")
    out = {
        "data_status": "REAL",
        "terrain_source": {"name": "NASA LRO LOLA LDEM_75S_240M (PDS Geosciences Node)", "version": f"PDS3 product {label_value(text, 'PRODUCT_VERSION_ID')}, created {label_value(text, 'PRODUCT_CREATION_TIME')}",
            "resolution_m": scale, "data_status": "REAL", "producer": "LRO LOLA team, NASA Goddard Space Flight Center",
            "url": "https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/data/lola_gdr/polar/img/ldem_75s_240m.img",
            "frame": "MEAN EARTH/POLAR AXIS OF DE421, heights above the 1737.4 km sphere", "observations": f"{label_value(text, 'START_TIME')} to {label_value(text, 'STOP_TIME')}"},
        "conversion": {"script": "scripts/build_lola_terrain.py", "converted_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "crop": f"{2 * k * scale / 1000:.1f} km square centred on the south pole, original {scale:.0f} m pixels, no resampling", "elevation_rounding_m": 0.5},
        "cols": cols, "rows": rows, "cell_size_m": scale, "origin_x_m": origin_x, "origin_y_m": origin_y, "row_order": "south_to_north_by_projected_y",
        "elevation_m": [round(float(v) * 2) / 2 for v in block.ravel()],
        "named_features": [dict(f, source="IAU name; centre coordinates approximate") for f in FEATURES],
    }
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, separators=(",", ":")))
    print(f"Wrote {a.out}: {cols} x {rows} cells at {scale:.0f} m, x {origin_x/1000:.1f}..{(origin_x + (cols-1)*scale)/1000:.1f} km, "
          f"heights {block.min():.0f}..{block.max():.0f} m")
    print("Feature check (crater floors should be far below the mirrored point):"); print("\n".join(checks))

if __name__ == "__main__":
    main()
