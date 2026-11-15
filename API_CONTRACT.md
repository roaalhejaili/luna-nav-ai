# API contract — version 1

Base URL: `http://localhost:8000`. JSON. UTC ISO 8601 timestamps with timezone (`Z` accepted). Lunar coordinates are **IAU_MOON_2015 planetocentric latitude and east-positive longitude**, degrees; longitude `[0,360)`. Elevation and route distance are meters; slopes degrees; durations hours. Elevation datum must be provided and reconciled by the real site service before scientific use; mock elevation is illustrative.

## Endpoints

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/health` | none | `{ "status":"ok", "mode":"standalone" }` |
| POST | `/mission/plan` | `Requirements` | `PlanResponse` |
| POST | `/mission/replan` | `{ "previous":PlanResponse, "requirements":Requirements }` | `PlanResponse` |
| POST | `/mission/compare` | `{ "requirements":Requirements }` | `{ "baseline":PlanResponse, "hybrid":PlanResponse, "metrics":object }` |

Request example: [`examples/demo_request.json`](examples/demo_request.json). Minimal valid request: `{"dates_utc":["2030-01-01T00:00:00Z"],"duration_hours":48}`. Structured fields take precedence over natural language. Dates and duration are mandatory. Priorities are nonnegative weights for `terrain`, `sunlight`, `communication`, `navigation`; at least one positive. Constraints: `max_slope_deg`, `min_sunlight_hours`, `max_blackout_hours`, `max_route_m`.

Response excerpt (other fields omitted):

```json
{"mission_id":"UUID","requirements":{"dates_utc":["2030-01-01T00:00:00Z"],"duration_hours":48},"candidates":[{"site":{"site_id":"A","latitude_deg":-89.1,"longitude_deg":45,"elevation_m":-1200,"slope_deg":6,"coordinate_frame":"IAU_MOON_2015: planetocentric latitude, east-positive longitude, mean Earth/polar axis","provenance":{"status":"MOCK","source":"LUNA Person 4 deterministic fixture","observed_at_utc":"2030-01-01T00:00:00Z"}},"visibility":{"site_id":"A","date_utc":"2030-01-01T00:00:00Z","sunlight_hours":36,"earth_visible_hours":33.6,"max_blackout_hours":12,"provenance":{"status":"MOCK","source":"fixture","observed_at_utc":"2030-01-01T00:00:00Z"}},"route":null,"feasible":true,"violations":[],"score":0.8,"explanation":"Feasible; synthetic data"}],"ranked_alternatives":[],"recommendation":null,"warnings":["MOCK data"],"limitations":[],"generated_at_utc":"2030-01-01T00:00:00Z","metrics":{"runtime_ms":1,"llm_calls":0,"tool_calls":2}}
```

The excerpt illustrates shape, not exact fixture values or ranking. Use `/openapi.json` for full required fields. `status` is `MOCK`, `VERIFIED`, or `UNVERIFIED`; every measurement has source, timestamp and uncertainty. `UNVERIFIED` is infeasible. `MOCK` is infeasible when `allow_mock_recommendation=false`. Successful requests with no feasible option return 200 with `recommendation:null` and warnings. Pydantic input errors return 422. Upstream or planning errors return 502 as `{"error":{"code":"UPSTREAM_OR_PLANNING_ERROR","message":"..."}}`.

## Real service contracts

Set URL environment variables separately. Person 1 actual API: `POST {LUNA_SITE_URL}/api/v1/landing-sites/candidates` with mission ID, target region, constraints and candidate count; `tools/member_adapters.py` maps its nested terrain result to `Site`. Person 2 actual API: `POST {LUNA_VISIBILITY_URL}/api/v1/visibility/analyze` with site coordinates, UTC start and duration days; the adapter maps terrain-aware summary fractions and blackout hours to `Visibility`. Person 3 actual API: `POST {LUNA_NAVIGATION_URL}/api/v1/routes` with start/target coordinates and max slope. Set `LUNA_NAV_TARGET_LAT` and `LUNA_NAV_TARGET_LON` when navigation is required; no destination is invented. Its live server and route adapter passed a MOCK integration test. Original contracts are under `original_modules/`. Models are in `schemas/models.py`. Navigation is queried only when requested. Supplier `MOCK` remains `MOCK`, while `REAL`/`PARTIAL`/`UNAVAILABLE` become `UNVERIFIED` rather than falsely claiming independent verification. HTTP errors and schema mismatches surface as 502; there is no invented fallback.
