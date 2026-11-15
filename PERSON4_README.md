# LUNA NAV AI — Person 4 Mission Optimizer (developer notes)

> Historical developer README. "MOCK" below describes the built-in demo fixtures used when no NASA services are configured. The submitted system runs on NASA data: see README.md.

Python 3.11+ standalone FastAPI service. All built-in values are **MOCK**, not lunar measurements. LangGraph coordinates supervisor, site, visibility, optional navigation, validation, optimization and explanation nodes. Optional structured LLM interpretation classifies mission type only; all measurements and scores come from deterministic services and code. No API key is required in mock mode.

## Run

```powershell
uv venv
uv pip install -r requirements.txt
uv run uvicorn api.main:app --reload
uv run pytest -q
```

POST `examples/demo_request.json` to `/mission/plan`, or open `/docs`. Set `LUNA_SITE_URL`, `LUNA_VISIBILITY_URL`, and `LUNA_NAVIGATION_URL` individually to replace mocks. `LUNA_HTTP_TIMEOUT_SECONDS` defaults to 10. No API key is required in mock mode.

## Team integration

Person 1–3 source is under `original_modules/`; the pristine Person 3 ZIP is retained at `original_modules/person3_original.zip`. The Person 3 integration copy changes only its Express core types dev dependency. Install Person 2's additional requirements with `uv pip install --python .venv/Scripts/python.exe -r original_modules/person2/member2/requirements.txt`. In `original_modules/person3/moon_navigation`, run `pnpm install --no-frozen-lockfile` and `pnpm approve-builds esbuild`. Run `powershell -ExecutionPolicy Bypass -File scripts/start_integrated.ps1` to launch the supplier APIs and this public API. Set `LUNA_NAV_TARGET_LAT`/`LUNA_NAV_TARGET_LON` for required navigation. Person 2's REAL mode may require NASA network access and LOLA/SPICE downloads. Supplier REAL is mapped to Person 4 UNVERIFIED pending independent scientific review. See `INTEGRATION_REPORT.md` and `FRONTEND_INTEGRATION_GUIDE.md`.

## Scoring

Hard constraints are evaluated before scoring. Feasible options use weighted utility: terrain `max(0,1-slope_deg/90)`; sunlight `min(1,sunlight_hours/duration_hours)`; communication `min(1,earth_visible_hours/duration_hours)`; navigation `max(0,1-distance_m/100000)` for accessible routes, otherwise zero. Divide weighted sum by sum of priority weights. The hybrid planner forms Pareto layers across active objectives, then SciPy MILP selects one actual site/date alternative at a time from each layer. The baseline ranks feasible options by weighted score. Comparison metrics are per-run observations, not a statistical superiority claim.

Replanning reuses visibility and route values only when site, date and mission duration match. Mock fixtures are synthetic and unsuitable for flight decisions.
