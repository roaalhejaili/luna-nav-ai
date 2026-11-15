"""LUNA NAV AI accuracy check: compare the running NASA-data pipeline against independent published values.

Run after scripts/start_real_nasa.ps1 is up (Person 1 :8001, Person 2 :8002, Person 4 :8000):
    .venv\\Scripts\\python.exe scripts\\accuracy_check.py
Writes accuracy_report.md and accuracy_report.json in the project root. Needs internet (Person 2 queries NASA/JPL Horizons).

References (independent of this code):
  [R1] Zuber et al., Nature 486 (2012) via MIT News: Shackleton is 21 km in diameter and 4.1 km deep (LOLA).
  [R2] NASA SVS 4716: Shackleton's floor is in perpetual shadow.
  [R4] NASA Artemis III candidate landing regions (announced 20 Aug 2022, each about 15 x 15 km); approximate centres
       as tabulated in Remote Sensing 17(9):1579 (2025), Table "Region Name / Longitude / Latitude".
  [R5] NASA LOLA official slope map LDSM_75S_240M (PDS GDR): slopes from plane fits to successive laser shots,
       30-120 m baseline, independent of our DEM-derived slopes.
  [R3] Glaser et al. (2018), table in "Peak of eternal light" (Wikipedia): illumination over lunar year 2020 at
       four points near Shackleton; computed on 20 m/pixel LOLA terrain.
Our terrain is 240 m/pixel, so tolerances are set wider than the references' own precision, and say so.
"""
import json, math, time, urllib.request, datetime
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
P1, P2, P4 = "http://127.0.0.1:8001", "http://127.0.0.1:8002", "http://127.0.0.1:8000"
LOLA = ROOT / "original_modules" / "person2" / "member2" / "data" / "lola" / "ldem_75s_240m.img"
R = 1737400.0; N = 3812; SCALE = 240.0; C0 = N / 2 - 0.5
results = []

def post(url, body, timeout=600):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r: return json.loads(r.read())

def record(name, status, measured, reference, tolerance, note=""):
    results.append(dict(check=name, status=status, measured=measured, reference=reference, tolerance=tolerance, note=note))
    print(f"[{status:4s}] {name}\n        measured: {measured}\n        reference: {reference}   tolerance: {tolerance}" + (f"\n        note: {note}" if note else ""))

def lola():
    return np.memmap(LOLA, dtype="<i2", mode="r", shape=(N, N))

def xy(lat, lon):
    rho = 2 * R * math.tan(math.radians(lat + 90) / 2); return rho * math.sin(math.radians(lon)), rho * math.cos(math.radians(lon))

def lola_h(dem, lat, lon):
    x, y = xy(lat, lon); i, j = x / SCALE + C0, C0 - y / SCALE; i0, j0 = int(i), int(j); fx, fy = i - i0, j - j0
    d = dem.astype(np.float64) if False else dem
    h = (d[j0, i0] * (1 - fx) + d[j0, i0 + 1] * fx) * (1 - fy) + (d[j0 + 1, i0] * (1 - fx) + d[j0 + 1, i0 + 1] * fx) * fy
    return float(h) * 0.5

def lola_slope(dem, lat, lon):
    x, y = xy(lat, lon); i, j = int(round(x / SCALE + C0)), int(round(C0 - y / SCALE))
    dzdx = (float(dem[j, i + 1]) - float(dem[j, i - 1])) * 0.5 / (2 * SCALE); dzdy = (float(dem[j - 1, i]) - float(dem[j + 1, i])) * 0.5 / (2 * SCALE)
    return math.degrees(math.atan(math.hypot(dzdx, dzdy)))

# ---------------------------------------------------------------- 1. terrain geometry
def check_shackleton_depth():
    dem = lola(); x0, y0 = xy(-89.67, 129.78); k = int(16000 / SCALE)
    ci, cj = int(round(x0 / SCALE + C0)), int(round(C0 - y0 / SCALE))
    block = dem[cj - k:cj + k + 1, ci - k:ci + k + 1].astype(float) * 0.5
    jj, ii = np.mgrid[-k:k + 1, -k:k + 1]; r = np.hypot(ii, jj) * SCALE
    floor = block[r < 3000].min()
    # rim crest: highest point along each of 72 radial profiles between 8 and 14 km, then averaged
    crests = []
    for a in np.linspace(0, 2 * np.pi, 72, endpoint=False):
        prof = [block[int(round(k + s * np.sin(a) / SCALE)), int(round(k + s * np.cos(a) / SCALE))] for s in np.arange(8000, 14000, SCALE)]
        crests.append(max(prof))
    depth = (np.mean(crests) - floor) / 1000; diam = None
    rim_r = []
    for a in np.linspace(0, 2 * np.pi, 72, endpoint=False):
        s = np.arange(6000, 15000, SCALE); prof = [block[int(round(k + t * np.sin(a) / SCALE)), int(round(k + t * np.cos(a) / SCALE))] for t in s]
        rim_r.append(s[int(np.argmax(prof))])
    diam = 2 * np.median(rim_r) / 1000
    record("Shackleton depth (rim crest mean minus floor), NASA LOLA 240 m", "PASS" if abs(depth - 4.1) <= 0.4 else "FAIL",
           f"{depth:.2f} km", "4.1 km [R1]", "±0.4 km (240 m pixels smooth the rim)")
    record("Shackleton rim diameter, NASA LOLA 240 m", "PASS" if abs(diam - 21) <= 2.5 else "FAIL", f"{diam:.1f} km", "21 km [R1]", "±2.5 km")

# ---------------------------------------------------------------- 2. illumination (Person 2: Horizons + LOLA horizon)
def p2(lat, lon, start, days, step=120):
    body = {"site": {"site_id": f"chk_{lat}_{lon}", "lat_deg": lat, "lon_deg_east": lon}, "start_utc": start, "duration_days": days,
            "step_minutes": step, "horizon_profile_id": "lola", "visibility_definition": "upper_limb", "include_time_series": False, "engine": "horizons"}
    t = time.time(); r = post(P2 + "/api/v1/visibility/analyze", body); return r, time.time() - t

def snap_to_peak(lat, lon, radius_px=6):
    """Published points mark local peaks on 20 m terrain; on the 240 m grid the same coordinate can fall on
    the peak's flank. Move to the highest LOLA cell within radius_px * 240 m and report the move."""
    dem = lola(); x, y = xy(lat, lon); i0, j0 = int(round(x / SCALE + C0)), int(round(C0 - y / SCALE)); best = None
    for dj in range(-radius_px, radius_px + 1):
        for di in range(-radius_px, radius_px + 1):
            if di * di + dj * dj > radius_px * radius_px: continue
            h = float(dem[j0 + dj, i0 + di]) * 0.5
            if best is None or h > best[0]: best = (h, di, dj)
    h, di, dj = best; X, Y = (i0 + di - C0) * SCALE, (C0 - (j0 + dj)) * SCALE; rho = math.hypot(X, Y)
    return -90 + math.degrees(2 * math.atan(rho / (2 * R))), math.degrees(math.atan2(X, Y)), math.hypot(di, dj) * SCALE, h - lola_h(dem, lat, lon)

def check_illumination():
    try:
        r, dt = p2(-89.67, 129.78, "2020-01-01T00:00:00Z", 354)
        s = r["summary"]["sun_visible_fraction_terrain"]
        record("Shackleton floor sunlit fraction, 2020 (Person 2: Horizons + LOLA horizon)", "PASS" if s <= 0.01 else "FAIL",
               f"{s * 100:.1f}% ({r['data_status']}, {dt:.0f} s)", "0% (permanent shadow) [R2]", "≤ 1%")
    except Exception as e: record("Shackleton floor sunlit fraction", "SKIP", str(e)[:160], "0% [R2]", "")
    for name, lat, lon, ref in [("A, Shackleton ridge", -89.68, -166.0, 81), ("B, peak near ridge", -89.44, -141.8, 82),
                                ("C, de Gerlache ridge", -88.71, -68.7, 85), ("D, peak near Shackleton", -88.79, 124.5, 86)]:
        try:
            plat, plon, moved, dh = snap_to_peak(lat, lon)
            r, dt = p2(round(plat, 5), round(plon, 4), "2020-01-01T00:00:00Z", 354); s = r["summary"]["sun_visible_fraction_terrain"] * 100
            record(f"Sunlit fraction at point {name}, lunar year 2020", "PASS" if abs(s - ref) <= 15 else "WARN" if abs(s - ref) <= 25 else "FAIL",
                   f"{s:.1f}% at the local peak ({plat:.4f}, {plon:.2f}), {moved:.0f} m from the published point and {dh:.0f} m higher ({dt:.0f} s)",
                   f"{ref}% [R3] at ({lat}, {lon})", "±15 points PASS, ±25 WARN",
                   "Published points are peaks on 20 m terrain; on the 240 m grid the exact coordinate lies on the flank, so the test uses the nearest LOLA peak within 1.4 km")
        except Exception as e: record(f"Sunlit fraction at point {name}", "SKIP", str(e)[:160], f"{ref}% [R3]", "")

# ---------------------------------------------------------------- 3. Person 1 terrain vs NASA LOLA 240 m
def check_person1():
    body = {"mission_id": "accuracy", "mission_type": "science",
            "target_region": {"body": "Moon", "coordinate_reference": "MEAN_EARTH_POLAR_AXIS", "projection": "EQUIRECTANGULAR",
                              "bounds": {"min_latitude_deg": -90, "max_latitude_deg": -87.5, "min_longitude_deg": -180, "max_longitude_deg": 180}},
            "constraints": {"max_slope_deg": 30, "max_roughness_m": 1e6}, "candidate_count": 6, "data_mode": "real",
            "start_utc": "2030-01-01T00:00:00Z", "duration_days": 2}
    try: r = post(P1 + "/api/v1/landing-sites/candidates", body, 120)
    except Exception as e: record("Person 1 elevations vs NASA LOLA 240 m", "SKIP", str(e)[:160], "", ""); return
    dem = lola(); de, ds = [], []
    for c in r["candidates"]:
        la, lo = c["coordinates"]["latitude_deg"], c["coordinates"]["longitude_deg"]
        de.append(c["terrain"]["elevation_m"] - lola_h(dem, la, lo)); ds.append(c["terrain"]["slope_deg"] - lola_slope(dem, la, lo))
    de, ds = np.array(de), np.array(ds)
    record(f"Person 1 elevation ({r['data_sources'][0]['product_id']}) minus LOLA 240 m, {len(de)} sites", "PASS" if np.abs(de).mean() <= 300 else "WARN",
           f"mean |diff| {np.abs(de).mean():.0f} m, max {np.abs(de).max():.0f} m", "same instrument, different gridding", "mean ≤ 300 m",
           f"Person 1 resolution {r['data_resolution_m']:.0f} m; both are heights above the 1737.4 km sphere")
    record("Person 1 slope minus LOLA 240 m slope", "INFO", f"mean {ds.mean():+.1f}°, mean |diff| {np.abs(ds).mean():.1f}°", "n/a",
           "", "Coarser grids report gentler slopes; differences show the resolution effect, not an error")

# ---------------------------------------------------------------- 3b. Person 1 picks vs NASA Artemis III regions
ARTEMIS = [("Peak Near Shackleton", -88.82, 123.37), ("Connecting Ridge", -89.05, -136.07), ("Connecting Ridge Extension", -89.0, -101.4)]

def gc_m(a, b):
    p1, p2 = math.radians(a[0]), math.radians(b[0]); dl = math.radians(b[1] - a[1])
    return 2 * R * math.asin(math.sqrt(math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2))

def check_artemis():
    body = {"mission_id": "accuracy-artemis", "mission_type": "science",
            "target_region": {"body": "Moon", "coordinate_reference": "MEAN_EARTH_POLAR_AXIS", "projection": "EQUIRECTANGULAR",
                              "bounds": {"min_latitude_deg": -90, "max_latitude_deg": -87.5, "min_longitude_deg": -180, "max_longitude_deg": 180}},
            "constraints": {"max_slope_deg": 15, "max_roughness_m": 1e6}, "candidate_count": 6, "data_mode": "real"}
    try: r = post(P1 + "/api/v1/landing-sites/candidates", body, 120)
    except Exception as e: record("Person 1 sites vs NASA Artemis III regions", "SKIP", str(e)[:160], "", ""); return
    rows, inside = [], 0
    for c in r["candidates"]:
        p = (c["coordinates"]["latitude_deg"], c["coordinates"]["longitude_deg"])
        name, d = min(((n, gc_m(p, (la, lo))) for n, la, lo in ARTEMIS), key=lambda t: t[1])
        inside += d <= 7500; rows.append(f"({p[0]:.3f},{p[1]:.1f}) {d / 1000:.1f} km from {name}")
    record("Person 1 candidate sites inside NASA Artemis III candidate regions", "PASS" if inside >= 1 else "WARN",
           f"{inside} of {len(rows)} within 7.5 km of a region centre; " + "; ".join(rows), "NASA Artemis III regions [R4]",
           "≥1 site inside a region", "Independent check: NASA chose these regions for sunlight, slope and Earth contact")

# ---------------------------------------------------------------- 3c. our slopes vs NASA official slope map
def check_slope_map():
    img = LOLA.with_name("ldsm_75s_240m.img"); lbl = img.with_suffix(".lbl")
    if not img.exists() or not lbl.exists():
        record("Our slopes vs NASA LOLA official slope map", "SKIP", "LDSM_75S_240M not downloaded", "[R5]", "",
               "Run: .venv\\Scripts\\python.exe scripts\\get_nasa_lola.py --product ldsm_75s_240m"); return
    import re
    t = lbl.read_text(encoding="latin-1"); val = lambda k, d=None: (re.search(rf"^\s*{k}\s*=\s*\"?([-+0-9.A-Za-z_]+)", t, re.M) or [None, d])[1]
    n = int(val("LINES")); sf = float(val("SCALING_FACTOR", 1)); off = float(val("OFFSET", 0)); bits = int(val("SAMPLE_BITS", 16))
    stype = val("SAMPLE_TYPE", "LSB_INTEGER"); dt = {8: "u1", 16: "i2", 32: "f4"}[bits]
    dt = (">" if stype.startswith("MSB") else "<") + (dt if not stype.endswith("UNSIGNED_INTEGER") or bits == 32 else dt.replace("i", "u"))
    nasa = np.memmap(img, dtype=dt, mode="r", shape=(n, n)).astype(np.float64) * sf + off
    dem = lola().astype(np.float64) * 0.5
    c = n / 2 - 0.5; k = int(76000 / SCALE)                                   # 90 S to ~87.5 S
    sl = (slice(int(c) - k, int(c) + k), slice(int(c) - k, int(c) + k))
    gy, gx = np.gradient(dem[sl], SCALE); ours = np.degrees(np.arctan(np.hypot(gx, gy))); ref = nasa[sl]
    ok = np.isfinite(ref) & (ref >= 0) & (ref <= 90)
    diff = ours[ok] - ref[ok]; corr = np.corrcoef(ours[ok], ref[ok])[0, 1]
    # agreement on the route-blocking decision at a 15 deg limit
    agree = np.mean((ours[ok] > 15) == (ref[ok] > 15)) * 100
    record("Our DEM-derived slope vs NASA official slope map (90 S to 87.5 S)", "PASS" if corr >= 0.7 else "WARN",
           f"correlation {corr:.2f}, mean difference {diff.mean():+.1f}°, mean |difference| {np.abs(diff).mean():.1f}°, same 15° pass/block decision on {agree:.1f}% of cells",
           "NASA LDSM_75S_240M [R5]", "correlation ≥ 0.7",
           "NASA slopes use a 30-120 m baseline, ours 240 m, so ours read gentler; the mean difference is the safety margin to subtract from slope limits")

# ---------------------------------------------------------------- 4. end-to-end Person 4
def check_end_to_end():
    req = {"request": "science mission near lunar south pole", "mission_type": "science", "dates_utc": ["2030-01-01T00:00:00Z"],
           "duration_hours": 48, "priorities": {"terrain": 1, "sunlight": 2, "communication": 2, "navigation": 0},
           "constraints": {"max_slope_deg": 15, "min_sunlight_hours": 0, "max_blackout_hours": 200}, "require_navigation": False}
    try: t = time.time(); r = post(P4 + "/mission/plan", req); dt = time.time() - t
    except Exception as e: record("End-to-end /mission/plan with NASA data", "SKIP", str(e)[:200], "", ""); return
    st = sorted({o["site"]["provenance"]["status"] for o in r["candidates"]} | {o["visibility"]["provenance"]["status"] for o in r["candidates"]})
    ok = all(o["visibility"]["sunlight_hours"] <= 48.001 and o["visibility"]["earth_visible_hours"] <= 48.001 for o in r["candidates"])
    record("End-to-end plan uses no MOCK values", "PASS" if "MOCK" not in st else "FAIL", f"statuses {st}; {len(r['candidates'])} candidates in {dt:.0f} s",
           "no MOCK", "", "UNVERIFIED = supplier REAL data not independently reviewed")
    record("Visibility hours stay within the stay length", "PASS" if ok else "FAIL", "all ≤ 48 h" if ok else "exceeded", "≤ 48 h", "")
    rec = r.get("recommendation")
    record("Recommendation", "INFO", f"{rec['site']['site_id']} sunlight {rec['visibility']['sunlight_hours']:.1f} h, Earth {rec['visibility']['earth_visible_hours']:.1f} h" if rec else "none", "", "", "; ".join(r["warnings"]))

if __name__ == "__main__":
    print("LUNA NAV AI accuracy check", datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"))
    check_shackleton_depth(); check_slope_map(); check_person1(); check_artemis(); check_illumination(); check_end_to_end()
    (ROOT / "accuracy_report.json").write_text(json.dumps(results, indent=1))
    md = ["# LUNA NAV AI accuracy report", "", "| Check | Result | Measured | Reference | Tolerance |", "|---|---|---|---|---|"]
    md += [f"| {r['check']} | {r['status']} | {r['measured']} | {r['reference']} | {r['tolerance']} |" for r in results]
    md += ["", "R1: Zuber et al., Nature 2012 (MIT News). R2: NASA SVS 4716. R3: Gläser et al. 2018 as tabulated on Wikipedia 'Peak of eternal light'. R4: NASA Artemis III candidate regions (2022), centres from Remote Sensing 17(9):1579. R5: NASA LOLA LDSM_75S_240M official slope map."]
    (ROOT / "accuracy_report.md").write_text("\n".join(md), encoding="utf-8")
    print("\nWrote accuracy_report.md and accuracy_report.json")
