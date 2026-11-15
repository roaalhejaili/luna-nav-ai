# Person 5 frontend API reference

Base URL: `http://127.0.0.1:8000`. Swagger: `/docs`; machine schema: `/openapi.json` (also exported as `openapi.json`). JSON timestamps are UTC ISO 8601. Site latitude/longitude are planetocentric degrees, east-positive longitude `[0,360)`, frame `IAU_MOON_2015` mean Earth/polar axis; distances and elevations meters, slopes degrees, durations hours. Person 2 adapter converts its `MOON_ME` frame to this equivalent Person 4 label. Do not treat `MOCK` or `UNVERIFIED` as certified NASA measurements.

| Method/path | Input | Output |
|---|---|---|
| `GET /health` | none | `{"status":"ok","mode":"standalone"}` |
| `POST /mission/plan` | `Requirements` (dates and duration required) | `PlanResponse` with candidates, ranked alternatives, recommendation, warnings |
| `POST /mission/replan` | `{"previous":PlanResponse,"requirements":Requirements}` | `PlanResponse`, same mission ID |
| `POST /mission/compare` | `{"requirements":Requirements}` | `{baseline:PlanResponse,hybrid:PlanResponse,metrics:object}` |

Request example: `examples/demo_request.json`. Full response examples: `FRONTEND_DATA_EXAMPLES/`. Required fields: `dates_utc` (1–30 UTC timestamps), `duration_hours` (>0). Optional `priorities` maps terrain/sunlight/communication/navigation to nonnegative weights; `constraints` supports `max_slope_deg`, `min_sunlight_hours`, `max_blackout_hours`, `max_route_m`; `require_navigation` controls route analysis. `allow_mock_recommendation=false` prevents provisional mock recommendations. The result `site.provenance.status`, `visibility.provenance.status`, and optional `route.provenance.status` are each `MOCK`, `UNVERIFIED`, or `VERIFIED`. Person 4 never upgrades supplier `REAL` to `VERIFIED` automatically.

Invalid request: HTTP 422 FastAPI validation detail. Upstream or planner failure: HTTP 502 `{"error":{"code":"UPSTREAM_OR_PLANNING_ERROR","message":"..."}}`. No feasible option: HTTP 200 with `recommendation:null`, empty `ranked_alternatives`, and warnings. Use the actual `openapi.json` for every field and type.
