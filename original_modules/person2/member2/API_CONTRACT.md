# API_CONTRACT.md: visibility_planner (Member 02, Solar & Earth Visibility Planner)

**Module:** `visibility_planner` · **Version:** 1.2.0 · **schema_version:** `1.1` (+ additive 1.2 fields: `observer_height_m`, `horizon.details`, `TERRAIN_UNAVAILABLE`)
**Owner:** Member 02 · **Consumers:** Member 04 (AI supervisor), Member 05 (dashboard), Member 03 (map)
**Supplier (optional):** Member 01 (terrain horizon profiles; this module already computes REAL ones from NASA LOLA)

This module answers: *from this lunar site, during this interval, when is the Sun up, when is the
Earth up (direct-to-Earth radio contact possible), and when is it dark or out of contact?* Every
number comes from NASA data. Nothing is invented.

**Data source:** by default (`engine: "auto"`) every request is computed live from the
**NASA/JPL Horizons API** (`https://ssd.jpl.nasa.gov/api/horizons.api`), the ephemeris tool named in
the Space Apps *Lunar Landing Site Navigator* challenge resources. The same numbers can also be computed
offline from NASA NAIF SPICE kernels (`"engine": "spice"`, after `scripts/fetch_kernels.py`); with the
default `auto`, that happens automatically when Horizons is unreachable. The two engines agree to
< 0.0002° in az/el and ≤ 2 s on window edges (tested).

**Terrain (real, NASA):** `"horizon_profile_id": "lola"` computes the site's true local horizon from
**NASA LRO LOLA `LDEM_75S_240M`** (laser-altimeter elevation grid, 75° S to the pole, 240 m/pixel,
NASA PDS Geosciences Node). For each of 360 azimuths the module walks 200 km outward across the grid
and keeps the steepest terrain angle (exact spherical geometry, observer `observer_height_m` above the
ground, default 2 m). Results are `data_status: "REAL"`. The 29 MB grid downloads once on first use
(or run `python scripts/fetch_lola.py`) into `data/lola/`. Sites north of 75° S → 422.


| `engine` | Data | Download | Speed (7 days, 10-min step) |
|---|---|---|---|
| `auto` (default) | Horizons; if unreachable (one 15 s try), local SPICE kernels when installed. After a failure, SPICE is used directly for 2 minutes. `data_source.fallback_reason` says so. | optional | about 5 s online, under 1 s offline |
| `horizons` | live NASA/JPL Horizons API only (error 503 if unreachable) | none | about 5 s (about 4–10 HTTPS calls, cached in memory) |
| `spice` | NASA NAIF SPICE kernels DE440s + MOON_ME only | about 44 MB once | about 0.1–1 s, works offline |

There are three ways to call it, and all three return the same JSON:

| Interface | How |
|---|---|
| REST | `uvicorn visibility_planner.api:app --port 8002` → `http://127.0.0.1:8002` (Swagger UI at `/docs`) |
| Python | `from visibility_planner import analyze_site, compare_windows` |
| CLI | `python -m visibility_planner --lat -86 --lon 0 --start 2026-11-15T00:00:00Z --days 7 --out r.json` |

Machine-readable JSON Schemas live in [`schemas/`](schemas/). The OpenAPI spec is served at `/openapi.json`.

---

## 1. Conventions (shared team rules)

| Item | Rule |
|---|---|
| Timestamps | UTC, ISO-8601. Outputs are always `YYYY-MM-DDTHH:MM:SSZ`. Inputs must carry a zone (`Z` or `+00:00`; other offsets are converted to UTC). **Naive datetimes are rejected (422).** |
| Angles | degrees |
| Distances, heights, altitude | meters (`alt_m`). Exception: `moon_radius_km` is labelled km. |
| Durations | hours (`duration_hours`, `longest_*_hours`); request durations in days (`duration_days`) |
| Fractions | 0..1 of the analysis interval |
| **Lunar reference frame** | **`MOON_ME`**, the Moon "Mean Earth / polar axis" body-fixed frame: z = mean rotation pole, x = mean direction to Earth. It is the frame of LOLA/LRO maps, NASA Moon Trek, and JPL Horizons (`MEAN_ME`). Implemented through `moon_de440_250416.tf` + `moon_pa_de440_200625.bpc`. |
| Moon shape | sphere, R = 1737.4 km (IAU mean radius; same as Horizons) |
| Latitude | planetocentric, **south negative**, [-90, 90] |
| Longitude | **east-positive**. Input accepts [-180, 360]; output normalised to [-180, 180) |
| Azimuth | clockwise from local north, [0, 360). At a pole, "north" = the meridian of the given longitude. |
| Elevation | above the local horizontal plane tangent to the sphere, [-90, 90] |
| `data_status` | `REAL` \| `MOCK` \| `PARTIAL` \| `UNAVAILABLE` (rules in §5) |

Compatibility promise: inside `schema_version 1.x`, fields may be **added**, but existing names,
types and units do not change. Clients should ignore unknown fields.

---

## 2. Endpoints

| Method | Path | Purpose | Success |
|---|---|---|---|
| GET | `/health?check_upstream=true` | Liveness/readiness. With `check_upstream=true` it pings JPL Horizons; `status` = `degraded` if unreachable. Lists `engines_available`. | 200 |
| GET | `/api/v1/visibility/meta` | Conventions, limits, kernel list, endpoint list | 200 |
| POST | `/api/v1/visibility/analyze` | One site + one interval → time series + windows + summary | 200 `VisibilityResult` |
| POST | `/api/v1/visibility/compare` | One site + 2..20 intervals → summaries side by side (no ranking) | 200 `ComparisonResult` |
| GET | `/api/v1/visibility/horizon-profiles` | List built-in synthetic horizon profiles | 200 |
| GET | `/api/v1/visibility/horizon-profiles/{profile_id}?site_id=` | One synthetic profile, in the exchange format | 200 / 404 |
| GET | `/api/v1/visibility/horizon-profiles/lola?lat=&lon=&site_id=&observer_height_m=` | REAL horizon computed from NASA LOLA for any site south of 75° S | 200 / 422 / 503 |
| GET | `/api/v1/visibility/mock?kind=analyze\|compare` | Labelled MOCK example response (works without kernels) | 200 |

Errors: 422 `VALIDATION_ERROR`, 404 `NOT_FOUND`, 502 `UPSTREAM_ERROR`, 503 `UPSTREAM_UNAVAILABLE` / `KERNELS_UNAVAILABLE`, 500 `INTERNAL_ERROR` (see §6).

Limits: `step_minutes` 0.5..1440, interval ≤ 400 days, ≤ 50 000 samples per request (sum over windows for compare).

---

## 3. `POST /api/v1/visibility/analyze`

### 3.1 Request: `VisibilityRequest` ([schema](schemas/visibility_request.schema.json))

| Field | Type | Req. | Default | Meaning |
|---|---|---|---|---|
| `site.site_id` | string | no | `"site"` | Your identifier; echoed back |
| `site.lat_deg` | float | **yes** | | latitude, deg, south negative |
| `site.lon_deg_east` | float | **yes** | | east longitude, deg |
| `site.alt_m` | float | no | 0 | height above the 1737.4 km sphere, meters |
| `start_utc` | ISO string | **yes** | | interval start, must have `Z`/offset |
| `end_utc` | ISO string | one of | | interval end |
| `duration_days` | float | one of | | interval length (give `end_utc` **or** `duration_days`) |
| `step_minutes` | float | no | 10 | sampling step; window edges are refined to ~1 s anyway |
| `visibility_definition` | `"center"`\|`"upper_limb"` | no | `"center"` | `center` = disk centre above the horizon (matches Horizons); `upper_limb` = any part of the disk above it |
| `horizon_profile` | HorizonProfile | no | null | inline terrain horizon (from Member 01). Mutually exclusive with `horizon_profile_id` |
| `horizon_profile_id` | `"lola"`\|`"flat"`\|`"ridge"`\|`"crater_rim"` | no | null | `lola` = **REAL** horizon from NASA LOLA at this site (south of 75° S); others = built-in **synthetic (MOCK)** profiles |
| `observer_height_m` | float 0..100 | no | 2.0 | for `lola`: observer (camera/antenna/panel) height above local terrain, meters |
| `include_time_series` | bool | no | true | set false for a small payload (summary + windows only) |
| `mission` | object | no | null | shared mission metadata (`mission_id`, `mission_type`, `target`, `constraints`, extra keys allowed). **Echoed back, not evaluated.** |
| `engine` | `"auto"`\|`"horizons"`\|`"spice"` | no | `"auto"` | data source: Horizons with automatic offline SPICE fallback (default), Horizons only, or SPICE only |
| `use_mock` | bool | no | false | return the labelled MOCK example instead of computing (works without network or kernels) |

Unknown top-level fields are rejected (422), so typos are caught.

```json
{
  "site": {"site_id": "site_A", "lat_deg": -86.0, "lon_deg_east": 0.0, "alt_m": 0.0},
  "start_utc": "2026-11-15T00:00:00Z",
  "duration_days": 7,
  "step_minutes": 10,
  "visibility_definition": "center",
  "horizon_profile_id": "ridge",
  "include_time_series": true,
  "mission": {"mission_id": "SCN-1", "mission_type": "science", "target": "lunar south pole",
              "constraints": {"max_dark_hours": 50, "max_no_contact_hours": 24}}
}
```

```bash
curl -X POST http://127.0.0.1:8002/api/v1/visibility/analyze -H "content-type: application/json" -d @examples/scenario_1.json
```

### 3.2 Response: `VisibilityResult` ([schema](schemas/visibility_result.schema.json))

Real output for the request above, abridged (`time_series` has 1009 rows; `assumptions`/`kernels` shortened):

```json
{
  "schema_version": "1.0",
  "module": "visibility_planner",
  "site_id": "site_A_near_side_86S",
  "body_frame": "MOON_ME",
  "moon_radius_km": 1737.4,
  "location": {"lat_deg": -86.0, "lon_deg_east": 0.0, "alt_m": 0.0},
  "start_utc": "2026-11-15T00:00:00Z",
  "end_utc": "2026-11-22T00:00:00Z",
  "step_minutes": 10.0,
  "visibility_definition": "center",
  "horizon": {"type": "terrain", "profile_id": "ridge", "data_status": "MOCK", "source": "synthetic_fixture"},
  "summary": {
    "sun_visible_fraction": 0.981608,
    "earth_visible_fraction": 1.0,
    "sun_visible_fraction_terrain": 0.981608,
    "earth_visible_fraction_terrain": 0.728535,
    "longest_dark_hours": 3.0899,
    "longest_no_contact_hours": 0.0,
    "longest_dark_hours_terrain": 3.0899,
    "longest_no_contact_hours_terrain": 45.6062,
    "sun_elevation_max_deg": 5.0227,
    "sun_elevation_mean_deg": 2.6799,
    "hours_until_sunset": null,
    "hours_until_earthset": null,
    "hours_until_sunset_terrain": null,
    "hours_until_earthset_terrain": null
  },
  "windows": [
    {"body": "sun", "kind": "geometric", "start_utc": "2026-11-15T03:05:24Z", "end_utc": "2026-11-22T00:00:00Z",
     "duration_hours": 164.9101, "starts_at_interval_start": false, "ends_at_interval_end": true},
    {"body": "dark", "kind": "geometric", "start_utc": "2026-11-15T00:00:00Z", "end_utc": "2026-11-15T03:05:24Z",
     "duration_hours": 3.0899, "starts_at_interval_start": true, "ends_at_interval_end": false},
    {"body": "no_contact", "kind": "terrain", "start_utc": "2026-11-15T00:00:00Z", "end_utc": "2026-11-16T21:36:22Z",
     "duration_hours": 45.6062, "starts_at_interval_start": true, "ends_at_interval_end": false}
  ],
  "time_series": [
    {"utc": "2026-11-15T00:00:00Z", "sun_az_deg": 114.4776, "sun_el_deg": -0.1001,
     "earth_az_deg": 357.3841, "earth_el_deg": 0.4425, "sun_visible": false, "earth_visible": true,
     "sun_visible_terrain": false, "earth_visible_terrain": false,
     "sun_horizon_el_deg": 0.0, "earth_horizon_el_deg": 2.9674}
  ],
  "assumptions": ["Moon modelled as a sphere of radius 1737.4 km; ...", "..."],
  "uncertainty": {"az_el_vs_jpl_horizons_deg": "max |diff| < 1e-5 deg over 174 reference rows ...",
                  "window_edge_refinement_s": 1.0, "sampling_step_minutes": 10.0, "...": "..."},
  "kernels": [],
  "data_source": {"engine": "horizons", "name": "NASA/JPL Horizons API (live)",
                  "url": "https://ssd.jpl.nasa.gov/api/horizons.api",
                  "ephemeris": "JPL Horizons observer ephemeris (DE441), apparent az/el, airless",
                  "moon_frame": "MEAN_ME high precision (= MOON_ME)", "requests": 4,
                  "download_required": false, "accessed_utc": "2026-11-14T09:02:11Z",
                  "fallback_reason": null},
  "mission": {"mission_id": "SCN-1", "mission_type": "science", "target": "lunar south pole",
              "constraints": {"max_dark_hours": 50, "max_no_contact_hours": 24}},
  "generated_utc": "2026-11-14T08:15:02Z",
  "data_status": "PARTIAL",
  "source": "NASA/JPL Horizons API (live observer ephemeris, MOON_ME/MEAN_ME); horizon: synthetic_fixture (MOCK)"
}
```

Field notes:

* `horizon.details` (LOLA only): `site_height_m` (terrain height at the site above the 1737.4 km sphere), `observer_height_m`, `max_range_m`, `step_m`, `min_ray_coverage_m`, `horizon_el_min_deg` / `horizon_el_max_deg`, `dem`.
* Terrain visibility can be **higher** than geometric: on a high ridge the real horizon dips below 0° (you look down over the surroundings), so the Sun stays visible longer than on a smooth sphere.
* `data_source` says which NASA data produced the numbers. `kernels` is filled only for `engine: "spice"`. With `engine: "auto"`, `data_source.fallback_reason` is set when SPICE was used because Horizons was unreachable.
* `hours_until_sunset` / `hours_until_earthset`: hours from `start_utc` to the first sunset/Earthset (time remaining for power / direct-to-Earth comms). They are `null` when the body is down at the start or does not set before `end_utc` (check `windows[].ends_at_interval_end`). The `_terrain` variants use the horizon profile.
* `sun_elevation_max_deg` / `sun_elevation_mean_deg`: solar elevation statistics over the samples (key power metric).

* `windows[].body`: `sun` (Sun up), `earth` (Earth up = direct-to-Earth line of sight), `dark` (Sun down), `no_contact` (Earth down).
* `windows[].kind`: `geometric` = smooth sphere, horizon at 0°; `terrain` = above the supplied horizon profile. `terrain` windows exist only when a horizon profile was given.
* For each `kind`, `sun` and `dark` windows exactly partition `[start_utc, end_utc]`, and so do `earth` and `no_contact`.
* `starts_at_interval_start` / `ends_at_interval_end`: the window was already running at the start, or still running at the end. Its true length may be longer than shown.
* `time_series[].sun_visible` / `earth_visible` are **geometric**. The `*_terrain` and `*_horizon_el_deg` fields are `null` without a horizon profile.
* `*_terrain` summary fields are `null` without a horizon profile.
* `generated_utc` is the only field that differs between identical requests.
* Window edges are refined by bisection to about 1 s, so they are not multiples of `step_minutes`.

---

## 4. `POST /api/v1/visibility/compare`

Same site and options, 2 to 20 candidate intervals. Returns numbers side by side. **This module does not rank or recommend.** That is Member 04's job.

Request (`CompareRequest`): `site`, `windows: [{label?, start_utc, end_utc | duration_days}]`, plus the optional `step_minutes`, `visibility_definition`, `horizon_profile` / `horizon_profile_id`, `mission`, `use_mock` described in §3.1.

```json
{
  "site": {"site_id": "site_A", "lat_deg": -86.0, "lon_deg_east": 0.0},
  "horizon_profile_id": "ridge",
  "step_minutes": 30,
  "windows": [
    {"label": "A", "start_utc": "2026-11-15T00:00:00Z", "duration_days": 7},
    {"label": "B", "start_utc": "2026-11-29T00:00:00Z", "duration_days": 7}
  ]
}
```

Response (`ComparisonResult`), real values, abridged:

```json
{
  "schema_version": "1.0", "module": "visibility_planner", "site_id": "site_A",
  "location": {"lat_deg": -86.0, "lon_deg_east": 0.0, "alt_m": 0.0}, "body_frame": "MOON_ME",
  "step_minutes": 30.0, "visibility_definition": "center",
  "horizon": {"type": "terrain", "profile_id": "ridge", "data_status": "MOCK", "source": "synthetic_fixture"},
  "windows": [
    {"label": "A", "start_utc": "2026-11-15T00:00:00Z", "end_utc": "2026-11-22T00:00:00Z", "duration_hours": 168.0,
     "summary": {"sun_visible_fraction": 0.981607, "longest_dark_hours": 3.09, "longest_no_contact_hours_terrain": 45.6061, "...": "..."},
     "data_status": "PARTIAL"},
    {"label": "B", "start_utc": "2026-11-29T00:00:00Z", "end_utc": "2026-12-06T00:00:00Z", "duration_hours": 168.0,
     "summary": {"sun_visible_fraction": 0.654632, "longest_dark_hours": 58.0219, "longest_no_contact_hours_terrain": 126.8236, "...": "..."},
     "data_status": "PARTIAL"}
  ],
  "table": {
    "sun_visible_fraction": [0.981607, 0.654632],
    "earth_visible_fraction": [1.0, 0.525784],
    "longest_dark_hours": [3.09, 58.0219],
    "longest_no_contact_hours": [0.0, 79.6683],
    "...": "one list per Summary field, same order as windows"
  },
  "data_status": "PARTIAL",
  "data_source": {"engine": "horizons", "name": "NASA/JPL Horizons API (live)", "...": "..."},
  "source": "NASA/JPL Horizons API (live observer ephemeris, MOON_ME/MEAN_ME); horizon: synthetic_fixture (MOCK)"
}
```

`table` is column-oriented so Member 04 can rank directly, for example `argmin(table["longest_dark_hours"])`.

---

## 5. `data_status` rules

| Situation | top-level `data_status` | `horizon.data_status` |
|---|---|---|
| NASA ephemeris (Horizons or SPICE), no horizon profile (geometric only) | `REAL` | `REAL` (smooth sphere) |
| NASA ephemeris + `horizon_profile_id: "lola"` (NASA LOLA terrain), or an inline profile with `data_status: "REAL"` | `REAL` | `REAL` |
| NASA ephemeris + synthetic/MOCK horizon profile | `PARTIAL` (geometric part real, terrain part mock) | `MOCK` |
| `use_mock: true` or `GET /mock` | `MOCK` | `MOCK` |
| Any error response | `UNAVAILABLE` | n/a |

Dashboards should show a visible badge when `data_status != "REAL"`.

---

## 6. Error response (every non-2xx) ([schema](schemas/error_response.schema.json))

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Request body failed validation.",
    "details": [
      {"field": "site.lat_deg", "message": "Input should be less than or equal to 90", "type": "less_than_equal"},
      {"field": "start_utc", "message": "Value error, datetime must be timezone-aware UTC, e.g. '2026-11-15T00:00:00Z' (naive datetimes are rejected)", "type": "value_error"}
    ]
  },
  "data_status": "UNAVAILABLE",
  "module": "visibility_planner",
  "schema_version": "1.0"
}
```

| HTTP | `code` | When |
|---|---|---|
| 422 | `VALIDATION_ERROR` | bad/missing field, naive datetime, lat out of range, end ≤ start, both or neither of `end_utc`/`duration_days`, too many samples, unknown `horizon_profile_id`, malformed JSON |
| 404 | `NOT_FOUND` | unknown profile id on `GET /horizon-profiles/{id}` |
| 503 | `UPSTREAM_UNAVAILABLE` | JPL Horizons unreachable (no internet, timeout, Horizons 5xx) after 3 tries. `details[0].hint`: retry, `engine: "auto"`/`"spice"`, or `use_mock: true` |
| 502 | `UPSTREAM_ERROR` | JPL Horizons answered but rejected the query or returned unexpected data |
| 503 | `TERRAIN_UNAVAILABLE` | `horizon_profile_id: "lola"` but the LOLA grid is missing and could not be downloaded. Hint: `python scripts/fetch_lola.py` |
| 422 | `VALIDATION_ERROR` | `lola` requested for a site north of 75° S (outside LOLA coverage) |
| 503 | `KERNELS_UNAVAILABLE` | `engine: "spice"` but kernels not downloaded. `details[0].hint` says to run `scripts/fetch_kernels.py` or send `use_mock: true` |
| 500 | `INTERNAL_ERROR` | unexpected bug |

The CLI uses exit codes instead: `0` ok, `2` invalid input, `3` kernels unavailable, `4` Horizons unavailable/error, `5` LOLA terrain unavailable (message on stderr).

---

## 7. Horizon profile exchange format (Member 01 → Member 02) ([schema](schemas/horizon_profile.schema.json))

Member 01 (terrain) should produce exactly this shape. Pass it inline as `horizon_profile`:

```json
{
  "site_id": "site_A",
  "profile_id": "site_A_lola_v1",
  "data_status": "REAL",
  "source": "LOLA LDEM 20 m/px, ray-cast 50 km, Member 01",
  "azimuth_deg":   [0.0, 1.0, 2.0, "... up to 359.0"],
  "elevation_deg": [2.97, 2.96, 2.93, "..."]
}
```

Rules: equal-length arrays with at least 2 points. Azimuth is in [0, 360), unique, in any order, clockwise from north in the MOON_ME frame at the site. Elevation is in [-90, 90] degrees, above the local horizontal of the **1737.4 km sphere**, so Member 01 must reference elevations to the same sphere. Interpolation is linear with wrap-around at 360→0. `data_status` must be `REAL` or `MOCK`. Recommended resolution is 1° or finer.

Built-in mock profiles: `flat` (0°), `ridge` (3° smooth ridge centred on north), and `crater_rim` (1–4° wall with a gap at az 160°). Get them from `GET /api/v1/visibility/horizon-profiles/{id}` or `tests/fixtures/horizon_*.json`.

---

## 8. Python function interface

```python
from visibility_planner import analyze_site, compare_windows, KernelError, UpstreamError
from pydantic import ValidationError

try:
    res = analyze_site({"site": {"lat_deg": -86, "lon_deg_east": 0},
                        "start_utc": "2026-11-15T00:00:00Z", "duration_days": 7})
except ValidationError as e:    # bad input -> same messages as the 422 details
    ...
except UpstreamError as e:      # Horizons unreachable (e.reachable False) or rejected query (True)
    ...
except KernelError as e:        # engine "spice" and kernels missing -> run scripts/fetch_kernels.py
    ...
payload = res.model_dump(mode="json")   # dict identical to the REST response
res.summary.longest_dark_hours          # typed access
```

`analyze_site(request: VisibilityRequest | dict, kernel_dir=None) -> VisibilityResult`
`compare_windows(request: CompareRequest | dict, kernel_dir=None) -> ComparisonResult`
`load_mock_response("mock_visibility_response.json" | "mock_compare_response.json") -> dict`

The functions are thread-safe: all CSPICE calls are serialised by one lock, and Horizons responses are cached per URL. A 7-day run at a 10-minute step takes about 5 s with Horizons and under 1 s with SPICE.

---

## 9. Dependencies

| Dependency | Needed for | Notes |
|---|---|---|
| Internet access to `ssd.jpl.nasa.gov` (NASA/JPL Horizons API) | default engine | no key, no download; Python standard library `urllib` |
| Python ≥ 3.10, `numpy`, `pydantic` v2, `spiceypy` | core | `pip install -r requirements.txt` (`spiceypy` is only used by `engine: "spice"`) |
| `fastapi`, `uvicorn`, `httpx` | REST API, API tests | |
| `matplotlib` | `examples/plot_visibility.py` only | |
| SPICE kernels (~44 MB, NASA NAIF) | **optional**: offline engine and `auto` fallback | `python scripts/fetch_kernels.py` → `data/spice_kernels/` (override with `LUNA_SPICE_KERNEL_DIR`) |
| NASA LOLA `LDEM_75S_240M` (29 MB, NASA PDS) | `horizon_profile_id: "lola"` | downloaded once on first use, or `python scripts/fetch_lola.py` → `data/lola/` (`LUNA_LOLA_DIR`; `LUNA_LOLA_AUTO_DOWNLOAD=0` disables auto-download). `truststore` lets Python use the Windows certificate store for that server. |
| Member 01 terrain | **optional** | can pass higher-resolution profiles inline as `horizon_profile` |
| Members 03/04/05 | **none** | this module calls no other module |

Environment variables: `LUNA_SPICE_KERNEL_DIR` (kernel folder) and `LUNA_CORS_ORIGINS` (comma-separated, default `*`).

## 10. Mock data for consumers who are offline

* `examples/mock_visibility_response.json`, `examples/mock_compare_response.json`: these exactly match the schemas, with `data_status: "MOCK"` and `data_source.engine: "mock"`. The numbers were copied from a live NASA/JPL Horizons run (site_A, ridge profile) and relabelled MOCK. Regenerate them with `python scripts/generate_fixtures.py`.
* `GET /api/v1/visibility/mock` or `"use_mock": true` returns the same payloads from a running server, even with no network or kernels.
