# NEXT_MEMBER_START_HERE.md: integrating with visibility_planner (Member 02)

You need about 10 minutes. The full contract is in [API_CONTRACT.md](API_CONTRACT.md).

## Step 0: You do NOT need my module running to start

Build against the mock files today:

* `examples/mock_visibility_response.json` (shape of `POST /api/v1/visibility/analyze`)
* `examples/mock_compare_response.json` (shape of `POST /api/v1/visibility/compare`)
* `schemas/*.schema.json` (JSON Schema for every request and response; generate TS/Python types from them)

Both mocks are labelled `"data_status": "MOCK"`. Show that label in your UI or logs. Never show it as real data.

## Step 1: Install and run (Windows PowerShell; on macOS/Linux use `source .venv/bin/activate`)

```bash
cd member2
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

**No data download is needed.** By default the module fetches Sun/Earth positions live from the NASA/JPL Horizons API (internet required). Optional, for offline use or the `auto` fallback, run this to download about 44 MB of NASA NAIF SPICE kernels:

```bash
python scripts/fetch_kernels.py
```

```bash
python -m pytest -q
```

Expected: `134 passed` with internet, SPICE kernels and the LOLA grid. With nothing downloaded and no internet, the network/kernel/LOLA tests skip with a reason.

```bash
uvicorn visibility_planner.api:app --host 127.0.0.1 --port 8002
```

Check it: `GET http://127.0.0.1:8002/health?check_upstream=true` should return `"status": "ok"` and `"horizons_reachable": true`. `"degraded"` means Horizons is unreachable from this machine; then use `"engine": "auto"` or `"spice"` (needs kernels), or mocks. Interactive docs are at `http://127.0.0.1:8002/docs`.

## Step 2: Integration recipe for your role

### Member 04 (AI supervisor), Python

Either call over HTTP, or import directly if you run in the same Python environment:

```python
# Option A: in-process (add member2/ to PYTHONPATH)
from visibility_planner import analyze_site, compare_windows
r = analyze_site({"site": {"site_id": cand.id, "lat_deg": cand.lat, "lon_deg_east": cand.lon},
                  "start_utc": mission.start_utc, "duration_days": mission.duration_days,
                  "include_time_series": False}).model_dump(mode="json")

# Option B: HTTP
import httpx
r = httpx.post("http://127.0.0.1:8002/api/v1/visibility/analyze", json=req, timeout=60).json()
if "error" in r: ...            # r["error"]["code"] in VALIDATION_ERROR / KERNELS_UNAVAILABLE / ...
```

Numbers to feed your scoring:

* `summary.longest_dark_hours`: compare with your power constraint (`max_dark_hours`)
* `summary.longest_no_contact_hours`: compare with your comms constraint
* `summary.sun_visible_fraction`, `summary.earth_visible_fraction`
* Prefer the `*_terrain` fields when they are not `null`, since they include local terrain.
* `summary.hours_until_sunset` / `hours_until_earthset`: time left for power / direct-to-Earth comms (null if down at start or no set before the end)
* `summary.sun_elevation_max_deg` / `sun_elevation_mean_deg`: solar elevation (power)
* Check `data_status`. Treat `PARTIAL`/`MOCK` results as provisional in your explanation. `data_source` tells you which NASA service produced the numbers.

For several launch dates at one site, call `/compare` and rank using `table[...]`. My module never ranks.

You can pass your mission object as `"mission"`. It is echoed back unchanged and is not evaluated here.

### Member 05 (dashboard), browser

* `fetch("http://127.0.0.1:8002/api/v1/visibility/analyze", {method: "POST", headers: {"content-type": "application/json"}, body: JSON.stringify(req)})`. CORS is open by default; restrict it with `LUNA_CORS_ORIGINS=http://localhost:5173`.
* Plot `time_series[].utc` against `sun_el_deg` / `earth_el_deg`. Draw the horizon as `sun_horizon_el_deg` / `earth_horizon_el_deg` when they are not null, and 0 otherwise.
* Shade `windows` where `kind == "terrain"` if a profile was used, else `kind == "geometric"`. `examples/plot_visibility.py` is a reference implementation.
* On a non-2xx response, show `error.message`. The response shape is always the same (API_CONTRACT §6). A 503 `UPSTREAM_UNAVAILABLE` means JPL Horizons is unreachable: offer a retry.
* Expect about 5 s per 7-day request (live NASA API), so show a loading state.
* While my server is down, load `examples/mock_visibility_response.json` and show a "MOCK" badge.

### Member 03 (map, `moon_explorer/`)

* Coordinates match Moon Trek: MOON_ME frame, latitude in degrees (south negative), **east-positive** longitude. When a user drops a pin, send `{lat_deg, lon_deg_east}` straight into `site`. If your map uses [-180, 180] longitude, that is accepted as is.
* To show a badge per pin, call `/analyze` with `"include_time_series": false` (small, fast response).

### Member 01 (terrain)

* **Already available:** REAL horizons from NASA LOLA `LDEM_75S_240M` (240 m/pixel) via `"horizon_profile_id": "lola"`, or `GET /api/v1/visibility/horizon-profiles/lola?lat=-86&lon=0`. Use it to cross-check your own terrain work. If you produce higher-resolution horizons (e.g. 5–20 m LOLA DEMs), send them inline as `horizon_profile`.
* **Site catalogue warning:** the team fixture "Shackleton rim (approx)" at −89.9°, 129.8° E lies about 336 m *below* the reference sphere, inside Shackleton's wall (34° slope to the south), not on the rim. Please correct it in your catalogue; well-lit points are e.g. the connecting ridge near −89.45°, −137.3° E.

* Produce horizon profiles in the format in API_CONTRACT §7 (`schemas/horizon_profile.schema.json`). Azimuth is clockwise from north. Elevation is in degrees relative to the local horizontal of the **1737.4 km sphere**.
* Mark them `"data_status": "REAL"` only when derived from real LOLA data. My output then becomes `REAL` instead of `PARTIAL`.
* There is no code dependency: the integrator (or Member 04) passes your profile inline as `horizon_profile` in my request. Validate your output with `HorizonProfile.model_validate(json)` from `visibility_planner.horizon`.

## Step 3: Final integration checklist

- [ ] Demo machine has internet: `GET /health?check_upstream=true` → `"horizons_reachable": true`.
- [ ] Offline safety net: kernels are in `member2/data/spice_kernels` (`scripts/fetch_kernels.py`). The default engine `auto` switches to them automatically if Horizons is unreachable.
- [ ] LOLA terrain grid present: `GET /health` → `"lola_dem_available": true` (else `python scripts/fetch_lola.py`, 29 MB).
- [ ] Run `python -m pytest -q` in `member2/` → all green.
- [ ] Run one real request per consumer and confirm `data_status` is `REAL` or `PARTIAL` (not `MOCK`).
- [ ] Once Member 01 delivers real profiles, replace `horizon_profile_id` with an inline `horizon_profile`.
- [ ] Port: 8002 by default. Tell the integrator if you change it.

## Who to ask

Member 02 owns `member2/`. Do not edit files there. Open an issue or message instead, so the contract stays stable (`schema_version 1.0`).
