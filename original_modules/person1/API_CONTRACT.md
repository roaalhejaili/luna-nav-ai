# API Contract — `landing_site_analyzer`

Version `v1`, module version `0.1.0`. The service is a terrain screening component for other LUNA NAV AI modules. It is independent of Persons 02–05.

## Conventions

- JSON field names are `snake_case`; JSON numbers are finite numeric values.
- All generated timestamps are UTC ISO-8601 with `Z` offset. Input `start_utc` is optional and, when supplied, must include a zero UTC offset.
- Coordinates are degrees; elevations, roughness, and resolution are meters; slope is degrees.
- Lunar frame is `MEAN_EARTH_POLAR_AXIS`: planetocentric latitude, east-positive longitude. API longitude bounds and outputs use `[-180, 180]`; the PDS cylindrical raster's `0–360°` east-positive longitudes are normalized during sampling. The output frame label is explicit. Projection contract label is `EQUIRECTANGULAR` (simple cylindrical/equirectangular raster grid).
- NASA LOLA heights are the PDS product's height values scaled from digital numbers, relative to the product's stated reference radius/datum; the API does not geoid-correct them.
- `data_status` is one of `REAL`, `MOCK`, `PARTIAL`, `UNAVAILABLE`. Analysis returns `REAL` for configured/read NASA PDS terrain and `MOCK` for the synthetic fixture; `PARTIAL` means a real raster produced fewer valid samples than requested; `UNAVAILABLE` means no terrain candidates were sampled. Health/info and error responses use `UNAVAILABLE` because they carry no analyzed terrain. Missing real data in explicit `real` mode is an HTTP error.
- Candidate coordinates are generated dynamically on a grid within the submitted region. Results are approximate screening samples, not safe landing-site certifications.

## Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/v1/health` | Process/API health |
| GET | `/api/v1/info` | Module capabilities and conventions |
| POST | `/api/v1/landing-sites/analyze` | Generate, evaluate, filter, and rank candidate sites |
| POST | `/api/v1/landing-sites/candidates` | Alias of analyze for candidate-focused callers |
| GET | `/api/v1/landing-sites/{site_id}` | Retrieve a candidate from the current process memory cache after analysis |

OpenAPI UI is `/docs`; machine-readable schema is `/openapi.json`.

## Analysis request

```json
{
  "mission_id": "mission_001",
  "mission_type": "lunar_landing",
  "target_region": {
    "body": "Moon",
    "coordinate_reference": "MEAN_EARTH_POLAR_AXIS",
    "projection": "EQUIRECTANGULAR",
    "bounds": {
      "min_latitude_deg": -10.0,
      "max_latitude_deg": 10.0,
      "min_longitude_deg": 20.0,
      "max_longitude_deg": 40.0
    }
  },
  "constraints": {
    "max_slope_deg": 10.0,
    "max_roughness_m": 2.0,
    "min_elevation_m": null,
    "max_elevation_m": null
  },
  "start_utc": "2026-11-14T09:00:00Z",
  "duration_days": 7.0,
  "candidate_count": 25,
  "data_mode": "auto"
}
```

`mission_id` is required. `target_region.bounds` are required; latitude must be within `[-90,90]`, longitude within `[-180,180]`; min latitude must be lower than max latitude. Longitude bounds can cross the antimeridian (for example `170` to `-170`). `constraints` defaults to 10° maximum slope and 2 m maximum roughness. Elevation limits are optional and interpreted against the LOLA product height datum. `candidate_count` is 1–500. `data_mode` is `auto`, `mock`, or `real`.

## Response

```json
{
  "mission_id": "mission_001",
  "module": "landing_site_analyzer",
  "body": "Moon",
  "generated_at_utc": "2026-11-14T06:00:00Z",
  "data_status": "MOCK",
  "data_sources": [
    {"name": "Deterministic synthetic test surface", "provider": "LUNA NAV AI local fixture", "url": null, "product_id": "synthetic-grid-v1"}
  ],
  "data_coverage": {"min_latitude_deg": -90.0, "max_latitude_deg": 90.0, "west_longitude_deg": -180.0, "east_longitude_deg": 180.0},
  "data_resolution_m": 30390.0,
  "data_limitations": ["Slope and roughness are estimated from a local 3x3 raster window and inherit the input DEM scale."],
  "coordinate_reference": "MEAN_EARTH_POLAR_AXIS",
  "units": {"coordinates": "degrees", "elevation": "m", "distance": "m", "slope": "degrees", "roughness": "m"},
  "candidates": [
    {
      "site_id": "site_0123456789ab",
      "coordinates": {"latitude_deg": 0.0, "longitude_deg": 30.0, "reference_frame": "MEAN_EARTH_POLAR_AXIS"},
      "terrain": {"elevation_m": 123.4, "slope_deg": 0.2, "roughness_m": 0.8},
      "suitability_score": 87.0,
      "score_components": {"slope": 98.0, "roughness": 60.0, "elevation": 100.0},
      "rank": 1,
      "selection_reasons": ["low local terrain slope"],
      "constraint_violations": [],
      "source": "Deterministic synthetic test surface",
      "resolution_m": 30390.0,
      "data_confidence": "LOW",
      "data_status": "MOCK"
    }
  ],
  "warnings": ["MOCK terrain is synthetic and is not a NASA measurement.", "Terrain suitability is a screening aid; it does not certify landing safety."]
}
```

The response's numeric values above illustrate structure only; mock values vary by candidate, and no NASA measurement is implied. Only candidates passing all constraints are returned if any are eligible. If none pass, all sampled candidates are returned with `constraint_violations` and a warning. A candidate source and status are repeated at site level to simplify downstream mapping and dashboards.

## Ranking and measurements

Slope and roughness scores are each `max(0, 100 × (1 - measured / configured_max))`. Elevation score is 100 when no elevation bound is set, 100 when within configured bounds, and 0 when outside. Suitability is `0.50 × slope_score + 0.30 × roughness_score + 0.20 × elevation_score`. Candidates with any violation are filtered when at least one candidate is eligible. Slope is calculated from a local 3×3 grid elevation gradient; roughness is standard deviation of valid elevations in that same 3×3 neighborhood. These scales inherit input DEM resolution and are not sub-pixel hazard detection.

`data_confidence` is a coarse resolution-only class: `LOW` at 1000 m/pixel or coarser, `MODERATE` above 100 m/pixel, and `HIGH` at or finer than 100 m/pixel. It is not a statistical uncertainty or safety confidence. `data_limitations` provides response-level scientific caveats; `warnings` includes per-analysis operational caveats.

## Errors

All API errors have an `error` object. Validation errors return 422:

```json
{"data_status":"UNAVAILABLE","error":{"code":"validation_error","message":"Request validation failed.","details":[{"field":"body.target_region.bounds.max_latitude_deg","message":"Input should be less than or equal to 90"}]}}
```

Explicit real-data mode with no configured/valid raster returns 503:

```json
{"data_status":"UNAVAILABLE","error":{"code":"terrain_data_unavailable","message":"No real DEM configured. Set LUNA_DEM_PATH and LUNA_DEM_LABEL_PATH"}}
```

Unknown site IDs return 404 (`site_not_found`) with `data_status: UNAVAILABLE`. Unexpected server errors return 500 (`internal_error`). The site lookup cache is process-local and is cleared on restart; call analyze first in the same service instance.

## Dependencies and Python interface

Dependencies: Python 3.11+, FastAPI, Uvicorn, NumPy. For an in-process call, use `from landing_site_analyzer.service import analyze` and pass a validated `MissionRequest` from `landing_site_analyzer.models`. The HTTP API is preferred for independently deployed team modules. There is no dependency on another member's code.
