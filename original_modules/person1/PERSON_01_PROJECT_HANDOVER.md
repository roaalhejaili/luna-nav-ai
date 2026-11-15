# LUNA NAV AI — Person 01 Project Handover

## 1. Project Overview

- **Project name:** LUNA NAV AI
- **Project concept:** Hybrid Multi-Agent Lunar Landing Site Navigator
- **Team role:** Person 01 — AI Landing Site Analyzer
- **Module:** `landing_site_analyzer`

This module is a terrain-only screening component. It accepts a lunar region and mission terrain constraints, samples terrain elevation, estimates local slope and roughness, filters and ranks generated candidates, and returns coordinates, explanations, constraint violations, data status, source metadata, resolution, confidence class, and limitations. It does not compute illumination, Earth visibility, final mission-wide optimization, or certified landing safety.

## 2. Architecture

```text
HTTP JSON request
      │
      ▼
FastAPI routes (app.py)
      │  Pydantic validation (models.py)
      ▼
Analysis service (service.py)
      ├── configured PDS IMG/LBL → decoded terrain grid (terrain.py)
      └── otherwise/forced → deterministic synthetic grid (terrain.py)
      │
      ▼
dynamic region samples → elevation / 3×3 slope / 3×3 roughness
      │
      ▼
constraints → terrain score → eligibility filter → ranked JSON response
```

`app.py` exposes the REST interface and standard error envelopes. `models.py` contains request and response schemas. `service.py` handles local data selection, candidate generation, constraint evaluation, scoring, ranking, and process-local site lookup. `terrain.py` parses a compatible PDS3 IMG plus detached LBL or produces deterministic MOCK terrain. Tests use FastAPI's test client and temporary PDS-style fixtures. There are no imports or runtime calls to Persons 02–05.

## 3. Complete File Structure

```text
project/
├── .gitignore
├── README.md
├── API_CONTRACT.md
├── DATA_SOURCES.md
├── NEXT_MEMBER_START_HERE.md
├── PERSON_01_PROJECT_HANDOVER.md
├── requirements.txt
├── landing_site_analyzer/
│   ├── __init__.py
│   ├── __main__.py
│   ├── app.py
│   ├── models.py
│   ├── service.py
│   └── terrain.py
└── tests/
    └── test_api.py
```

- `.gitignore`: excludes Python virtual environments, bytecode, and pytest cache.
- `README.md`: quick installation, configuration, API, and test instructions.
- `API_CONTRACT.md`: versioned JSON schema, endpoints, example payloads, errors, score formula, units, and frame.
- `DATA_SOURCES.md`: official challenge resource inventory, PDS/LOLA source details, verification status, and limitations.
- `NEXT_MEMBER_START_HERE.md`: commands and handoff steps for each other team module.
- `PERSON_01_PROJECT_HANDOVER.md`: this full technical handover.
- `requirements.txt`: runtime and test dependencies.
- `landing_site_analyzer/__init__.py`: package metadata/version.
- `landing_site_analyzer/__main__.py`: standalone Uvicorn launcher on `127.0.0.1:8000`.
- `landing_site_analyzer/app.py`: FastAPI app, routes, and error handlers.
- `landing_site_analyzer/models.py`: Pydantic inputs, outputs, validation, enums, and UTC serialization.
- `landing_site_analyzer/service.py`: configurable data selection, candidate generation, scoring, ranking, warnings, and in-memory lookup.
- `landing_site_analyzer/terrain.py`: PDS IMG/LBL reader, grid sampling/derivatives, and deterministic synthetic grid.
- `tests/test_api.py`: ten API, validation, mock, terrain, and PDS fixture tests.

The existing `outputs/` and `work/` folders contained no project source and are excluded from the archive. No `.venv`, caches, downloaded DEM, credentials, or token files are included.

## 4. Implemented Features

### Terrain data processing

`load_pds_img` accepts an uncompressed PDS3 16-bit integer IMG and detached label. It validates files, dimensions, sample width/type, expected byte length, scale factor, map resolution, cylindrical projection, and the mean-Earth coordinate label. It reads byte order, pixel scale, resolution, map projection offsets, center latitude/longitude, and optional missing-value markers from the label. It scales digital numbers to the product's height values in meters. It does not add the label's reference-radius offset to the returned height and does not geoid-correct the values.

The initial adapter supports mean-Earth simple-cylindrical products; it does not support arbitrary raster formats, polar stereographic imagery, reprojection, or automatic network downloads.

### Elevation, slope, and roughness

- Elevation is the nearest valid raster cell, in meters.
- Slope is estimated from a local 3×3 pixel elevation gradient, with an approximate lunar spherical metric conversion and output in degrees.
- Roughness is the standard deviation of valid elevation values in that 3×3 neighborhood, in meters. It is a prototype local variability metric and is not claimed to equal the archived LOLA roughness layer.
- Grid coverage is derived from the raster dimensions and projection offsets. Sampling outside the supported grid or over missing/non-finite terrain returns no sample. The analysis response reports grid latitude/longitude coverage and equatorial pixel spacing.
- A data-confidence class is resolution-only: `LOW` at ≥1000 m/pixel, `MODERATE` above 100 m/pixel, otherwise `HIGH`. It is explicitly not statistical uncertainty.

### Dynamic generation, filtering, and ranking

The requested latitude/longitude bounds are divided into an approximately even grid to produce up to `candidate_count` sample locations; there is no hardcoded landing-site list. Antimeridian-crossing longitude bounds are supported. Each sampled candidate receives a stable hash-derived `site_id` based on mission ID and coordinates.

Configurable constraints include maximum slope, maximum roughness, and optional minimum/maximum elevation. Constraint violations are named in `constraint_violations`. When one or more candidates meet every constraint, violating candidates are filtered out of the returned recommendation list. When none meet all constraints, sampled candidates are returned with violations and a warning. `selection_reasons` gives short terrain-based rationale text.

Score components are:

- `slope_score = max(0, 100 × (1 − slope / max_slope))`
- `roughness_score = max(0, 100 × (1 − roughness / max_roughness))`
- `elevation_score = 100` when no elevation limit is specified or it is satisfied; `0` when a configured elevation limit is violated.
- `suitability_score = 0.50 × slope_score + 0.30 × roughness_score + 0.20 × elevation_score`

Lower numeric score is more suitable under these configured thresholds; the service ranks descending. When no elevation bounds are supplied, the neutral elevation component is 100. This is a configurable screening heuristic, not a landing safety guarantee.

### Mock mode

The deterministic synthetic surface is generated in `mock_grid()` in code. `data_mode: "mock"` forces it. Default `"auto"` uses configured local PDS data when it loads and otherwise selects mock data, labeling it `MOCK` and returning a warning. `"real"` requires a configured readable DEM and returns HTTP 503 if unavailable. Synthetic numbers are never described as NASA measurements.

## 5. NASA Data Sources

### Official challenge resources

The official Space Apps Resources tab was opened and inspected. It lists ASU LROC QuickMap, NASA/JPL Moon Trek, JPL Horizons, and the Canadian Space Agency Moon Exploration portal. QuickMap and Moon Trek can help visually inspect lunar terrain; the challenge resource list does not itself provide a raw LOLA download endpoint. Moon Trek publishes an OGC REST WMTS tile API; the tile products are map imagery, not the raw numeric grid used by this code. Horizons is an ephemeris service and belongs to Person 02's solar/Earth visibility work. CSA Moon Exploration is background reference material.

### Operational terrain source

- **Dataset:** LRO LOLA Gridded Data Record, including cylindrical `LDEM_16`.
- **Provider:** NASA Planetary Data System Geosciences Node / LOLA instrument team.
- **Directory:** `https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/data/lola_gdr/cylindrical/img/`
- **Example files:** `ldem_16.img` and the matching detached `ldem_16.lbl`.
- **Format:** PDS3 16-bit signed-integer binary IMG and text LBL; the reader relies on label metadata.
- **Coverage/reference:** global simple/equirectangular cylindrical coverage for LDEM_16, planetocentric latitude and east-positive longitude, in the LOLA mean-Earth/polar-axis convention. API longitudes are normalized to `[-180,180]`.
- **Resolution:** 16 pixels/degree, about 1.895 km/pixel at the equator; the PDS listing shows 33,177,600 bytes for the IMG.
- **Height units:** meters from the label scaling factor, relative to the product's stated reference radius; no geoid correction is applied.
- **Use/access:** the PDS directory is publicly listed without a key requirement in the source listing. Preserve the PDS source/product citation and applicable PDS usage guidance.

### Access and processing status

| Item | Status |
|---|---|
| Official Space Apps Resources tab | Accessed in browser; resource names and descriptions recorded in `DATA_SOURCES.md`. |
| Moon Trek / WMTS docs | Identified and documentation read; no WMTS layer was downloaded or used in this module. |
| LOLA PDS directory and SIS | Source metadata and formats identified from official listings/documentation. |
| NASA IMG/LBL download | Attempted from the published PDS URL; failed with a Windows TLS credential error. No NASA data file is included. |
| NASA data processing | Not verified. Tests use a tiny generated PDS-format fixture only, not a NASA product. |
| Mock surface | Implemented locally and labeled `MOCK`; deterministic synthetic data only. |

LDEM_16's roughly 1.9 km equatorial spacing cannot resolve meter-scale landing hazards. The returned slope and roughness inherit input resolution, and polar east-west metric conversion is approximate. No result certifies a site as safe.

## 6. REST API Documentation

Base URL: `http://127.0.0.1:8000`; prefix `/api/v1`. FastAPI Swagger UI: `/docs`; OpenAPI JSON: `/openapi.json`.

### Shared analysis request

```json
{
  "mission_id": "mission_001",
  "mission_type": "lunar_landing",
  "target_region": {
    "body": "Moon",
    "coordinate_reference": "MEAN_EARTH_POLAR_AXIS",
    "projection": "EQUIRECTANGULAR",
    "bounds": {"min_latitude_deg": -10, "max_latitude_deg": 10, "min_longitude_deg": 20, "max_longitude_deg": 40}
  },
  "constraints": {"max_slope_deg": 10, "max_roughness_m": 2.0},
  "start_utc": "2026-11-14T09:00:00Z",
  "duration_days": 7,
  "candidate_count": 25,
  "data_mode": "mock"
}
```

`mission_id`, `target_region`, and bounds are required. `candidate_count` is 1–500. Constraints default to 10° slope and 2 m roughness. `start_utc` and `duration_days` are accepted optional metadata; this terrain-only module does not use them in calculations. `data_mode` is `auto`, `mock`, or `real`.

Example response fields:

```json
{
  "mission_id": "mission_001",
  "module": "landing_site_analyzer",
  "body": "Moon",
  "generated_at_utc": "2026-11-14T09:01:00Z",
  "data_status": "MOCK",
  "data_sources": [{"name": "Deterministic synthetic test surface", "provider": "LUNA NAV AI local fixture", "url": null, "product_id": "synthetic-grid-v1"}],
  "data_resolution_m": 30390.0,
  "data_coverage": {"min_latitude_deg": -90, "max_latitude_deg": 90, "west_longitude_deg": -180, "east_longitude_deg": 180},
  "data_limitations": ["Slope and roughness inherit the input DEM scale."],
  "coordinate_reference": "MEAN_EARTH_POLAR_AXIS",
  "units": {"coordinates": "degrees", "elevation": "m", "distance": "m", "slope": "degrees", "roughness": "m"},
  "candidates": [{
    "site_id": "site_example",
    "coordinates": {"latitude_deg": 0.0, "longitude_deg": 30.0, "reference_frame": "MEAN_EARTH_POLAR_AXIS"},
    "terrain": {"elevation_m": 100.0, "slope_deg": 0.2, "roughness_m": 0.8},
    "suitability_score": 87.0,
    "score_components": {"slope": 98.0, "roughness": 60.0, "elevation": 100.0},
    "rank": 1,
    "selection_reasons": ["low local terrain slope"],
    "constraint_violations": [],
    "source": "Deterministic synthetic test surface",
    "resolution_m": 30390.0,
    "data_confidence": "LOW",
    "data_status": "MOCK"
  }],
  "warnings": ["MOCK terrain is synthetic and is not a NASA measurement."]
}
```

Values in this example illustrate structure and are not NASA measurements; mock outputs vary by sampled location.

### 1. Health

- **Method/URL:** `GET /api/v1/health`
- **Purpose:** report that the API process is responsive.
- **Parameters/request JSON:** none.
- **Example response:** `{"status":"ok","module":"landing_site_analyzer","api_version":"v1","data_status":"UNAVAILABLE"}`. `UNAVAILABLE` means this health response contains no analyzed terrain.
- **Errors:** no module-specific error is defined; infrastructure failures may return 500.
- **Dependencies:** running FastAPI process only.

### 2. Module info

- **Method/URL:** `GET /api/v1/info`
- **Purpose:** describe capability names, frame, units, and out-of-scope calculations.
- **Parameters/request JSON:** none.
- **Example response:** `{"module":"landing_site_analyzer","version":"0.1.0","body":"Moon","data_status":"UNAVAILABLE","coordinate_reference":"MEAN_EARTH_POLAR_AXIS","coordinate_units":"degrees","terrain_units":{"elevation":"m","slope":"degrees","roughness":"m"}}` (the actual response also includes capability and `does_not_compute` arrays).
- **Errors:** no module-specific error is defined; infrastructure failures may return 500.
- **Dependencies:** running FastAPI process only.

### 3. Mission analysis

- **Method/URL:** `POST /api/v1/landing-sites/analyze`
- **Purpose:** generate terrain samples, apply constraints, score and rank eligible sites.
- **Parameters/request JSON:** the shared analysis request shown above.
- **Example response:** the shared candidate response shown above.
- **Errors:** 422 `validation_error`; 503 `terrain_data_unavailable` when explicit real mode lacks valid local raster inputs; 500 `internal_error` for unexpected failures. Error body is `{"data_status":"UNAVAILABLE","error":{"code":"...","message":"..."}}`; validation errors also include `details`.
- **Dependencies:** FastAPI/Pydantic; NumPy for PDS/mock processing; local DEM only in real mode.

### 4. Candidate generation alias

- **Method/URL:** `POST /api/v1/landing-sites/candidates`
- **Purpose:** candidate-focused alias of mission analysis; uses the same scoring and response schema.
- **Parameters/request JSON:** identical to `/analyze`.
- **Example response:** identical to the shared candidate response.
- **Errors/dependencies:** identical to `/analyze`.

### 5. Candidate lookup

- **Method/URL:** `GET /api/v1/landing-sites/{site_id}`
- **Purpose:** retrieve a candidate created by analysis in this process.
- **Parameters/request JSON:** path parameter `site_id`; no JSON body.
- **Example response:** one candidate object with `site_id`, coordinates, terrain, score, rank, reasons, violations, source, resolution, confidence, and status.
- **Errors:** 404 `site_not_found`, with `data_status: UNAVAILABLE`, if not in the in-memory cache; 500 infrastructure/unexpected errors.
- **Dependencies:** prior analysis in the same running process. Cache is not durable across restarts or multiple workers.

## 7. API Contracts and Integration

- JSON field names use `snake_case`.
- Coordinates use degrees. `latitude_deg` is planetocentric lunar latitude. Longitude is east-positive and returned/bounded in `[-180,180]`; the cylindrical source grid uses `0–360°` and is normalized for API access.
- Reference frame: `MEAN_EARTH_POLAR_AXIS` (the LOLA product label may identify the realization as Mean Earth/Polar Axis of DE421). Projection label: `EQUIRECTANGULAR`, corresponding to the source's simple/equirectangular cylindrical map.
- Elevation and roughness are meters; slope is degrees; resolution/distance are meters.
- Generated timestamps are UTC ISO-8601 strings ending in `Z`. Optional input `start_utc` must have an explicit zero UTC offset.
- `data_status`: `REAL`, `MOCK`, `PARTIAL`, or `UNAVAILABLE`. Health/info/errors use `UNAVAILABLE` because no analyzed terrain is included.
- Validation error example: `{"data_status":"UNAVAILABLE","error":{"code":"validation_error","message":"Request validation failed.","details":[{"field":"body...","message":"..."}]}}`.
- The response contains `data_sources`, product ID, URL, resolution, coverage, warnings, and limitations for downstream provenance display.
- `GET /landing-sites/{site_id}` is only a local in-process convenience; consumers should retain the analysis response for durable integration.

## 8. Dependencies and Technologies

Actual dependencies in `requirements.txt`:

| Package | Purpose |
|---|---|
| Python 3.11+ | Runtime; uses modern union type syntax. |
| FastAPI | HTTP routes, OpenAPI schema, and request/response integration. |
| Uvicorn (`standard` extras) | Local ASGI server and standalone launch. |
| NumPy | DEM array decoding/sampling, missing-value handling, mock grid, slope and roughness calculations. |
| Pytest | Test runner. |
| HTTPX | FastAPI `TestClient` transport used by API tests. |
| Pydantic (transitive via FastAPI) | Request/response validation and UTC serialization. |

Rasterio and SciPy are not used by the implementation. No external team package is required.

## 9. Testing and Verification

There are **10 test functions** in `tests/test_api.py`:

1. `test_health_and_info_contract` — health and module-info routes/frame.
2. `test_mock_analysis_dynamic_candidates_and_units` — mock analysis response shape, dynamic candidate count, coordinates, data status, timestamp, coverage, confidence, and limitations.
3. `test_candidate_alias_and_site_lookup` — candidate route alias and process-local site retrieval.
4. `test_invalid_request_uses_standard_error_envelope` — 422 validation envelope.
5. `test_unknown_site_has_standard_error_envelope` — 404 lookup envelope.
6. `test_real_mode_without_dem_returns_503` — explicit real mode missing-data failure.
7. `test_pds_label_decoder_and_sampling` — temporary PDS IMG/LBL scale parsing and sample.
8. `test_invalid_pds_byte_length_rejected` — malformed raster rejection.
9. `test_constraints_filter_candidates_and_report_violations` — candidate constraint fallback and violation reporting.
10. `test_terrain_derivatives_are_finite_and_nonnegative` — terrain elevation, slope, and roughness calculation outputs.

**Actual execution result:** tests were not executed. `python -m pytest -q` and `py -3.11 -m pytest -q` both failed before pytest launch because neither `python` nor `py` is installed/discoverable in the current environment. The API was not started, and no endpoint was runtime-tested. Do not read the presence of the test file as a passing test result.

**NASA data verification:** no NASA raster was downloaded or processed. The PDS reader test uses an in-memory temporary fixture created by the test. An attempted PDS file download failed with a Windows TLS credential error.

## 10. How to Install and Run (Windows PowerShell)

From the project directory, with Python 3.11+ installed:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pytest -q
python -m landing_site_analyzer
```

Then open Swagger at `http://127.0.0.1:8000/docs`. The launch command is `python -m landing_site_analyzer`; the default mode is mock/automatic. To use a local DEM, set `$env:LUNA_DEM_PATH` and optionally `$env:LUNA_DEM_LABEL_PATH` before starting the API.

## 11. Integration Guide for the Other Four Members

- **Person 02 — Solar & Earth Visibility Planner:** call `POST /api/v1/landing-sites/analyze`; pass candidate `site_id`, latitude, longitude, frame, and mission times into the visibility planner. This module does not calculate solar or Earth angles/windows.
- **Person 03 — Smart Moon Maps & Navigation:** plot the returned coordinates using `MEAN_EARTH_POLAR_AXIS`; display terrain elevation/slope/roughness with units, data status, source, and resolution. Avoid silently mixing map layers in a different frame.
- **Person 04 — Hybrid Multi-Agent Mission Optimizer:** call the REST API as a tool or use `from landing_site_analyzer.service import analyze` with a validated `MissionRequest`. Consume score components, violations, reasons, source, status, and limitations. The score is a terrain specialist output only.
- **Person 05 — Mission Simulator & Dashboard:** call the analyze route and render ranked candidates, terrain properties, selection reasons, constraint violations, source, resolution, warnings, and confidence/status labels. Keep `MOCK` data visually distinct from `REAL`.

No other module is assumed present. For separate processes, REST is preferred. In-process function interface is available, but the site cache remains local to one process.

## 12. Current Limitations and Remaining Work

- No Python runtime was available in the authoring environment; dependency installation, tests, and API startup remain unverified.
- The PDS source was identified and documented, but direct IMG/LBL download failed on Windows TLS credentials. Real-data parsing against an actual NASA product remains unverified.
- Only labeled PDS3 16-bit mean-Earth cylindrical IMG input is supported; no generic GeoTIFF, JP2, polar projection, or coordinate reprojection.
- The module expects users to obtain the raster/label pair locally. It does not automatically download/update NASA data.
- Slope and roughness are approximations from a 3×3 raster neighborhood; coarse input resolution and local-metric approximation limit scientific use, especially near poles.
- Resolution-only confidence is a simple category, not a measured uncertainty estimate.
- Candidate lookup cache is process-local and nonpersistent. Multiple workers/restarts do not share it.
- Rejected candidates are only returned when there are no eligible candidates; if any pass, only eligible candidates appear in the response.
- No other team module has been integrated or tested because their implementations are not present.
- Runtime packages are declared but were not installed in this environment.

## 13. Final Delivery Status

| Area | Status |
|---|---|
| Code implementation | Implemented as a new standalone Python package; runtime unverified here. |
| API implementation | Five routes and schema/error handling implemented; server not started here. |
| Mock-data functionality | Implemented and covered by tests; tests not executed in this environment. |
| NASA data integration | PDS LOLA IMG/LBL reader implemented; no real NASA data downloaded or processed. |
| Tests | Ten tests written; execution blocked because Python is unavailable. |
| Documentation | README, API contract, data-source inventory, next-member guide, and this handover report created. |
| Integration readiness | Interfaces and contracts are ready for other modules to consume; runtime integration remains unverified and NASA real-data validation is outstanding. |
