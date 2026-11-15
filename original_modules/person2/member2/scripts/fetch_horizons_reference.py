"""Fetch independent reference Sun/Earth azimuth+elevation values from NASA/JPL Horizons.

Run:  python scripts/fetch_horizons_reference.py
Writes tests/fixtures/horizons_reference.json. Your own SPICE results are compared to this in tests.
Horizons uses the high-precision Moon mean-Earth frame (MEAN_ME) with an airless Moon, no refraction,
and reports apparent azimuth (clockwise from north) / elevation of the target CENTER, in degrees.
Standard library only. Query parameters were tested in a browser on 2026-11-14.
"""
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://ssd.jpl.nasa.gov/api/horizons.api"
OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "horizons_reference.json"

# (name, east longitude deg, latitude deg). Approximate fixture sites, NOT an authoritative catalog.
SITES = [("south_far_side", 129.8, -86.0), ("south_near_side", 0.0, -86.0), ("pole_rim", 129.8, -89.9)]
BODIES = {"sun": "10", "earth": "399"}
START, STOP, STEP = "2026-11-15 00:00", "2026-11-22 00:00", "6 h"


def query(cmd: str, lon: float, lat: float):
    params = {
        "format": "text", "COMMAND": f"'{cmd}'", "OBJ_DATA": "'NO'", "MAKE_EPHEM": "'YES'",
        "EPHEM_TYPE": "'OBSERVER'", "CENTER": "'coord@301'", "SITE_COORD": f"'{lon},{lat},0'",
        "COORD_TYPE": "'GEODETIC'", "START_TIME": f"'{START}'", "STOP_TIME": f"'{STOP}'",
        "STEP_SIZE": f"'{STEP}'", "QUANTITIES": "'4'", "CSV_FORMAT": "'YES'",
        "ANG_FORMAT": "'DEG'", "TIME_TYPE": "'UT'",
    }
    url = API + "?" + urllib.parse.urlencode(params)
    text = urllib.request.urlopen(url, timeout=60).read().decode()
    block = re.search(r"\$\$SOE(.*?)\$\$EOE", text, re.S)
    if not block:
        raise RuntimeError("Horizons returned no ephemeris:\n" + text[:500])
    rows = []
    for line in block.group(1).strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        rows.append({"time": parts[0], "az_deg": float(parts[3]), "el_deg": float(parts[4])})
    return rows


if __name__ == "__main__":
    data = {"source": "NASA/JPL Horizons API", "frame": "MEAN_ME (high precision)",
            "start_utc": START, "stop_utc": STOP, "step": STEP, "sites": {}}
    for name, lon, lat in SITES:
        data["sites"][name] = {"lon_deg_east": lon, "lat_deg": lat,
                               **{b: query(c, lon, lat) for b, c in BODIES.items()}}
        print("fetched", name)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=1))
    print("wrote", OUT)
