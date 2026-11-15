# NEXT MEMBER START HERE — Person 01 API

This module can run alone. It does not import Persons 02, 03, 04, or 05. Start with mock mode for integration work; replace mock terrain only when an agreed NASA PDS DEM and label are configured.

## 1. Install and start

From the project root in PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m landing_site_analyzer
```

The service listens at `http://127.0.0.1:8000`. Browse `http://127.0.0.1:8000/docs` for interactive API documentation and `http://127.0.0.1:8000/openapi.json` for generated OpenAPI. Confirm startup with `GET /api/v1/health`.

## 2. Make a mock analysis call

```powershell
$body = @{
  mission_id = "integration_smoke_001"
  target_region = @{
    body = "Moon"
    coordinate_reference = "MEAN_EARTH_POLAR_AXIS"
    projection = "EQUIRECTANGULAR"
    bounds = @{ min_latitude_deg = -15; max_latitude_deg = -5; min_longitude_deg = 20; max_longitude_deg = 35 }
  }
  constraints = @{ max_slope_deg = 10; max_roughness_m = 2 }
  candidate_count = 20
  data_mode = "mock"
} | ConvertTo-Json -Depth 6
$result = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/landing-sites/analyze -ContentType application/json -Body $body
$result.candidates | Format-Table rank, site_id, suitability_score
```

All returned candidates state `data_status: MOCK`; downstream consumers must preserve that label. To test a real source explicitly, configure `LUNA_DEM_PATH` and `LUNA_DEM_LABEL_PATH`, then use `data_mode: real`. This mode returns 503 rather than silently substituting mock data if loading fails. `auto` permits mock fallback and includes a warning.

## 3. Module hand-offs

- **Person 02 (Sun/Earth visibility):** send each candidate's `site_id`, `coordinates.latitude_deg`, `coordinates.longitude_deg`, `coordinates.reference_frame`, and mission dates. Your service owns visibility/window outputs; do not reinterpret terrain `suitability_score` as illumination quality.
- **Person 03 (Moon map/navigation):** plot candidate latitude/longitude using the stated mean-Earth/polar-axis frame. Display terrain units as `elevation_m`, `slope_deg`, and `roughness_m`; show `data_status`, `source`, and `resolution_m` in details.
- **Person 04 (mission optimizer):** consume the response's candidates, score components, constraint violations, reasons, provenance, and status as a terrain-specialist result. The score is terrain-only; combine it with other objectives in your optimizer.
- **Person 05 (dashboard/simulator):** render `rank`, `suitability_score`, terrain values, coordinate values, selection reasons, source, resolution, `data_confidence`, `data_limitations`, warnings, and status. Keep MOCK visibly distinguishable from REAL.

## 4. Stable interface details

- `POST /api/v1/landing-sites/analyze` is the primary interface.
- `POST /api/v1/landing-sites/candidates` is an alias for candidate-oriented clients.
- `GET /api/v1/landing-sites/{site_id}` retrieves a site only in the same running process after analysis. Treat it as a convenience; persist the analyze response if cross-process durability is needed.
- Requests use degree bounds and meters/degrees for terrain constraints. `mission_id` is your shared cross-module correlation key.
- Validation failures return HTTP 422 with `{"data_status":"UNAVAILABLE","error":{"code":"validation_error",...}}`; no configured real data returns 503; unknown site ID returns 404 with `data_status: UNAVAILABLE`.
- Candidate sites are dynamic samples of the submitted region. This prototype is not a precision landing planner and makes no safety guarantee.

## 5. Run tests

```powershell
python -m pytest -q
```

Tests cover health/info, request validation, API response shape, mock mode, lookup, real-mode missing data, and PDS label/image fixture processing. They do not download the NASA dataset.

## 6. Relevant files

- `landing_site_analyzer/app.py`: FastAPI endpoints and error envelopes.
- `landing_site_analyzer/models.py`: validated shared JSON schemas.
- `landing_site_analyzer/service.py`: dynamic sampling, filtering, score, rank, cache.
- `landing_site_analyzer/terrain.py`: PDS IMG/LBL loader and mock fixture.
- `API_CONTRACT.md`: full wire contract.
- `DATA_SOURCES.md`: verified source details and real-data limitations.
