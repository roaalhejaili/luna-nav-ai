# NEXT_MEMBER_START_HERE.md - Connecting to Module 03 (`moon_navigation`)

Module 03 runs on its own. You do not need any other member's code. Everything it returns today is `MOCK` (synthetic terrain) until a real DEM is plugged in.

## A. Run it (2 minutes)
```bash
cd moon_navigation
npm install
npm start                 # API on http://localhost:3003/api/v1
npm run dev:web           # Moon Explorer UI on http://localhost:5173 (proxies /api to :3003)
npm test                  # 30 tests: geometry, pathfinding, API, fixtures
```
Quick check: `curl http://localhost:3003/api/v1/health` -> `"status":"ok"`.

## B. Use it from your module (pick what you need)

**Module 04 (mission_optimizer) - navigation tool**
1. Call `POST http://localhost:3003/api/v1/routes` with the body from `fixtures/route_request.example.json`.
2. Read `alternatives[].distance_m / max_slope_deg / mean_slope_deg / warnings`.
3. Always forward `data_status` and `operational_validity` to your explanation step. Never state MOCK numbers as real.
4. No network? Load `fixtures/route_response.example.json` as your mock tool response (same shape as the real API).

**Module 05 (mission_dashboard) - map data**
1. Pins: `GET /sites`. Terrain layer: `GET /terrain/grid?step=2`. Routes: `POST /routes`.
2. Handle errors by `error.code` (see API_CONTRACT.md, section 1): show `OUT_OF_COVERAGE` and `NO_ROUTE_FOUND` as user messages, not crashes.
3. Offline mock: `fixtures/sites.mock.json`, `fixtures/route_response.example.json`, `fixtures/error.out_of_coverage.example.json`.

**Module 01 (landing_site_analyzer) - feed sites to the map**
1. Serve `GET <your-url>` returning `{ "sites": [ { "site_id", "location": {"lat_deg","lon_deg"}, "terrain", "reason", "source", "data_status" } ] }` (Site Output shape, see API_CONTRACT.md).
2. Start Module 03 with `LANDING_SITES_URL=<your-url> npm start`.
3. Check `GET /sites`: `upstream` should be `landing_site_analyzer`. If it says `mock`, read `warnings` - it tells you why (unreachable, HTTP error, or contract mismatch).

**Module 02 (visibility_planner)** - no direct dependency today. Use the same Location object (`lat_deg`, `lon_deg`, `elevation_m`, `frame: "IAU_MOON_ME"`) so site coordinates match.

## C. Rules that must not change without telling everyone
- Timestamps UTC ISO-8601; angles in degrees; lengths in meters; frame `IAU_MOON_ME`.
- Field names: `lat_deg`, `lon_deg`, `elevation_m`, `slope_deg`, `distance_m`, `data_status`.
- `data_status` is one of `REAL | MOCK | PARTIAL | UNAVAILABLE`.
- Error body is always `{ error: {code, message, details?}, request_id, timestamp_utc }`.
- Changing a response shape = update `API_CONTRACT.md`, `fixtures/*.json` and the tests in the same commit. `tests/fixtures.test.ts` and `tests/api.test.ts` will fail if they drift.

## D. Swapping the fixture for real NASA terrain (owner of Module 03)
1. Implement a loader that returns the `TerrainGrid` interface from `src/server/terrain.ts` (`cols, rows, cellSizeM, originX, originY, elevation, slope, source`) in the same south-polar stereographic meters (see `projectSouthPolar` in `src/server/geo.ts`).
2. Set `source.data_status` to `"REAL"` and pass the grid to `createApp({ grid })` in `src/server/index.ts`.
3. Update the mock site positions in `src/server/sitesProvider.ts` (or rely on Module 01 via `LANDING_SITES_URL`) and rerun `npm test`. Tests that assert `MOCK` will need to be adjusted for the real grid.

## E. Files
| Path | Purpose |
|---|---|
| `src/server/` | REST API (`app.ts`), validation (`schemas.ts`), errors (`errors.ts`), projection + distance (`geo.ts`), fixture terrain (`terrain.ts`), A*/Dijkstra (`pathfinding.ts`), routes (`routeService.ts`), sites + Module 01 fallback (`sitesProvider.ts`) |
| `src/web/` | Moon Explorer UI: pan/zoom, pins, search, terrain layers, route alternatives, distance measuring |
| `src/shared/types.ts` | TypeScript contract types |
| `fixtures/` | Example requests/responses to use as mocks |
| `tests/` | Vitest + supertest |
