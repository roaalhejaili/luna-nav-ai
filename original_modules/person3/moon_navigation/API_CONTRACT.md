# API_CONTRACT.md - Module 03 `moon_navigation`

LUNA NAV AI - Smart Moon Maps & Navigation. Contract version **1.0.0**.
Base URL (local default): `http://localhost:3003/api/v1`

> Status of data: the terrain used today is a **synthetic fixture** (not NASA data). Every response that depends on it carries `"data_status": "MOCK"`. Do not present MOCK results as real.
> Routes are exploratory, terrain-slope-only estimates. `operational_validity` is always `"NOT_VALIDATED"`.

## 1. Conventions (shared by all modules)

| Item | Rule |
|---|---|
| Timestamps | ISO-8601 **UTC**, e.g. `2026-11-14T08:13:57.677Z` (`generated_at_utc`, `timestamp_utc`) |
| Angles / coordinates | **degrees**: `lat_deg` in [-90, 90] (north +), `lon_deg` in [-180, 180] (east +) |
| Distances, elevations | **meters** (`*_m`) |
| Frame | `IAU_MOON_ME` (IAU Moon Mean Earth / Polar Axis selenographic frame) |
| Reference sphere | R = **1 737 400 m**. `elevation_m` = meters above this sphere |
| Map projection (display only) | `LUNA_SP_STEREO`: south-polar stereographic on that sphere, true scale at the pole, central meridian 0 deg. PROJ: `+proj=stere +lat_0=-90 +lat_ts=-90 +lon_0=0 +k=1 +x_0=0 +y_0=0 +R=1737400 +units=m +no_defs`. Also served at `GET /meta/frame` |
| Distances | great-circle (haversine) on the reference sphere. Planar projected x/y are never used for distance |
| `data_status` | `REAL` \| `MOCK` \| `PARTIAL` \| `UNAVAILABLE` |
| Request id | optional request header `x-request-id`; always echoed in the response header and body |
| Unknown request fields | rejected (`400 VALIDATION_ERROR`) |

### Location (shared object)
```json
{ "lat_deg": -88.811008, "lon_deg": -56.309932, "elevation_m": 1821.4, "frame": "IAU_MOON_ME" }
```
Inputs may omit `elevation_m` and `frame`; if `frame` is given it must be `IAU_MOON_ME`. Outputs always include all four fields (`elevation_m` may be `null` outside terrain coverage).

### Site (Module 01 "Site Output" shape)
```json
{
  "site_id": "MOCK-SP-01",
  "name": "Mock Site A (NW plateau)",
  "location": { "lat_deg": -88.811008, "lon_deg": -56.309932, "elevation_m": 1821.4, "frame": "IAU_MOON_ME" },
  "terrain": { "elevation_m": 1821.4, "slope_deg": 1.84, "roughness_m": null },
  "reason": "Low slope on a broad rise (fixture).",
  "source": "moon_navigation mock fixture",
  "data_status": "MOCK"
}
```

### Error envelope (all errors)
```json
{
  "error": { "code": "OUT_OF_COVERAGE", "message": "start point (-70, 0) is outside the supported terrain coverage.", "details": {} },
  "request_id": "d5dcc647-f0f7-470a-a547-bd6b58f45a4a",
  "timestamp_utc": "2026-11-14T08:13:57.879Z"
}
```
| HTTP | `error.code` | When |
|---|---|---|
| 400 | `VALIDATION_ERROR` | bad/missing field, out-of-range value, unknown field. `details` = `[{path, message}]` |
| 400 | `INVALID_JSON` | body is not valid JSON |
| 404 | `NOT_FOUND` | unknown path |
| 422 | `OUT_OF_COVERAGE` | point outside terrain coverage. `details.coverage` describes the covered area |
| 422 | `NO_ROUTE_FOUND` | no path satisfies the slope limit |
| 500 | `INTERNAL_ERROR` | unexpected failure |

## 2. Endpoints

### `GET /health`
Liveness + identity. Response: `{ status: "ok", module: "moon_navigation", module_id: "03", api_version, terrain_source, dependencies, data_status, request_id, generated_at_utc }`.

### `GET /meta/frame`
Returns frame, units, reference radius and the map projection definition (see section 1).

### `GET /terrain/coverage`
Supported area: `projected_extent_m [minX,minY,maxX,maxY]`, `corners` (lat/lon), `max_latitude_deg`, `cell_size_m`, `terrain_source`. Current fixture: 100 km x 100 km around the south pole, 500 m cells (edge midpoints reach about -88.35 deg latitude, corners about -87.67 deg).

### `GET /terrain/sample?lat_deg=-89&lon_deg=0`
```json
{ "location": { "lat_deg": -89, "lon_deg": 0, "elevation_m": 1205.2, "frame": "IAU_MOON_ME" },
  "terrain": { "elevation_m": 1205.2, "slope_deg": 0.08, "roughness_m": null },
  "terrain_source": { "name": "...", "version": "fixture-1.0.0", "resolution_m": 500, "data_status": "MOCK" },
  "data_status": "MOCK" }
```
Errors: 400 validation, 422 `OUT_OF_COVERAGE`.

### `GET /terrain/grid?step=4`
Downsampled raster for terrain layers (`step` 1-20). Returns `cols, rows, cell_size_m, origin_x_m, origin_y_m` (projected meters of cell (0,0)), `elevation_m[]`, `slope_deg[]` (row-major, rows ordered south to north by projected y).

### `GET /sites`
Candidate sites for pins. If env `LANDING_SITES_URL` (Module 01) is set, the module calls it (2 s timeout), validates the body (`{ "sites": [Site...] }`) and returns those sites (`upstream: "landing_site_analyzer"`). On timeout / HTTP error / contract mismatch it **falls back to MOCK sites** and adds a message to `warnings`. Response: `{ sites: Site[], upstream: "mock" | "landing_site_analyzer", warnings: string[], data_status, ... }`. `data_status` is `REAL` only when every site is `REAL` and nothing was dropped, otherwise `PARTIAL`/`MOCK`.

### `POST /distance`
Request: `{ "points": [Location, Location, ...] }` (2-2000 points).
```json
{ "method": "great_circle_haversine", "reference_sphere_radius_m": 1737400,
  "distance_m": 30323.4, "surface_distance_m": 30323.4,
  "segment_distances_m": [30323.4], "notes": [], "data_status": "MOCK", "request_id": "...", "generated_at_utc": "..." }
```
`distance_m` = horizontal great-circle length. `surface_distance_m` additionally includes elevation change (known elevations only).

### `POST /routes`  (Route Output)
Request:
```json
{
  "start":  { "lat_deg": -88.811008, "lon_deg": -56.309932 },
  "target": { "lat_deg": -88.833164, "lon_deg": 132.70939 },
  "constraints": { "max_slope_deg": 15 },
  "algorithm": "astar",
  "strategies": ["shortest", "balanced", "gentle"]
}
```
Defaults: `max_slope_deg` 15 (0-45), `algorithm` `astar` (or `dijkstra`), `strategies` all three. Both algorithms return the same optimal cost; A* expands fewer nodes. Cells steeper than the limit are never entered (start/target cells are exempt and produce a warning).

Response (waypoints shortened here; full example in `fixtures/route_response.example.json`):
```json
{
  "route_id": "uuid", "request_id": "uuid", "generated_at_utc": "2026-11-14T08:14:00.000Z",
  "data_status": "MOCK", "frame": "IAU_MOON_ME", "algorithm": "astar",
  "start": { "lat_deg": -88.811008, "lon_deg": -56.309932, "elevation_m": 1821.4, "frame": "IAU_MOON_ME" },
  "target": { "lat_deg": -88.833164, "lon_deg": 132.70939, "elevation_m": 711.8, "frame": "IAU_MOON_ME" },
  "max_slope_limit_deg": 15,
  "alternatives": [
    {
      "alt_id": "shortest-1", "strategy": "shortest",
      "distance_m": 74555.4, "straight_line_distance_m": 71215.4,
      "max_slope_deg": 13.65, "mean_slope_deg": 2.98,
      "elevation_gain_m": 607.2, "elevation_loss_m": 1716.8,
      "waypoints": [ { "lat_deg": -88.811008, "lon_deg": -56.309932, "elevation_m": 1821.4, "frame": "IAU_MOON_ME" }, { "lat_deg": -89.765648, "lon_deg": -129.289407, "elevation_m": 667.6, "frame": "IAU_MOON_ME" } ],
      "warnings": ["Terrain is MOCK: SYNTHETIC south-pole fixture (not NASA data).", "Route reaches 13.7 deg, close to the 15 deg limit."]
    }
  ],
  "terrain_source": { "name": "...", "version": "fixture-1.0.0", "resolution_m": 500, "data_status": "MOCK" },
  "operational_validity": "NOT_VALIDATED",
  "disclaimers": ["Routes are exploratory terrain-only estimates. Operational validity is NOT validated.", "..."]
}
```
(Only the first two of the 45 waypoints are shown; the file `fixtures/route_response.example.json` holds the full response format with 3 waypoints per alternative.) Strategies: `shortest` ignores slope except the hard limit; `balanced` and `gentle` increasingly penalize steep cells. If some strategies find no path they are omitted and named in `disclaimers`; if none do, `422 NO_ROUTE_FOUND`.

## 3. Dependencies

| Dependency | Required? | Behavior when absent |
|---|---|---|
| Module 01 `landing_site_analyzer` (`LANDING_SITES_URL`) | No | MOCK sites, `warnings` explains |
| Module 02 visibility | No | not used |
| Module 04 / 05 | No | they call **this** module |
| Real NASA DEM | Not yet | synthetic fixture, everything `MOCK` |

Environment: `PORT` (default 3003), `LANDING_SITES_URL` (optional), web dev: `VITE_API_TARGET` (default `http://localhost:3003`), `VITE_API_BASE` (default `/api/v1`).

## 4. Who calls what
- **Module 04 (optimizer)**: tool "Navigation analysis" -> `POST /routes` (read `alternatives[].distance_m`, `max_slope_deg`, `warnings`; check `data_status`).
- **Module 05 (dashboard)**: `GET /sites`, `GET /terrain/grid`, `POST /routes`; or embed the Moon Explorer UI (`src/web`).
- **Module 01**: expose `GET <LANDING_SITES_URL>` returning `{ "sites": [Site...] }`.

## 5. Known limits
- Fixture terrain is synthetic; coordinates near the south pole only (see `/terrain/coverage`).
- Slope uses central differences on a 500 m grid; real DEM data will change values.
- No illumination, communication, rock-hazard or traverse-dynamics modeling.
- Planar grid steps use projected meters (scale error under 0.05% inside the fixture); reported distances use great-circle math.
