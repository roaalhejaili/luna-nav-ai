# LUNA NAV AI — Mission Command (Person 5 frontend)

A cinematic mission-planning UI on top of the real Person 4 planner (`/mission/plan`, `/mission/replan`, `/mission/compare`) and Person 3's Moon navigation module. Plain HTML, CSS and ES modules: no build step, no npm packages and no internet needed. No backend code was changed.

## Run

```powershell
# 1. Mission planner (Person 4), from the project root
.venv\Scripts\python.exe -m uvicorn api.main:app --port 8000

# 2. This UI, on port 5173 (the planner's default CORS origin)
cd frontend; py -m http.server 5173
# open http://localhost:5173

# 3. Optional: Person 3 navigation module (live terrain + route API)
cd original_modules\person3\moon_navigation; pnpm start    # port 3003
```

Without step 3 everything still works. The 3D terrain, routes and safety simulation then use a bundled snapshot of Person 3's terrain fixture, and the UI says so. Other ports: `http://localhost:5173/?api=http://HOST:8000&nav=http://HOST:3003/api/v1`.

## Real NASA terrain (LOLA)

The 3D Moon, LUNA WALK, rover routes and the safety simulation use **real NASA elevation data** when `data/lola_south_pole.json` exists (it is included). It was built from NASA LRO LOLA `LDEM_75S_240M` (PDS Geosciences Node, product V2.0): a 160 × 160 km square around the south pole at the original 240 m pixels. To rebuild it yourself:

```powershell
.venv\Scripts\python.exe scripts\get_nasa_lola.py        # downloads the 29 MB NASA file (resumable)
.venv\Scripts\python.exe scripts\build_lola_terrain.py   # writes frontend\data\lola_south_pole.json
```

The build script prints a check that Shackleton, Shoemaker, de Gerlache and Haworth come out as deep depressions, which confirms the map is not mirrored. Terrain priority in the app: NASA LOLA grid, then Person 3 live grid, then the bundled Person 3 fixture. The badge says which one is in use. The planner's own sites and visibility values are still the backend's mock fixtures until Persons 1 and 2 run in real mode. The site panel shows the real LOLA elevation and slope at each planner site next to the planner's mock values. Person 3's demo destination sites were designed for its synthetic terrain, so the safety simulation snaps each destination and sample point to the nearest drivable ground and shows how far it moved it.

## The journey

| Step | What happens | Where the numbers come from |
|---|---|---|
| Command cabin | Spacecraft interior, Moon and Earth through the window, START MISSION. The status lights are live health checks. | Planner `/health`, Person 3 `/health` |
| 01 Mission | Four objectives (scientific, astronaut, rover, long-duration). Each one sets the priority weights that drive the ranking. Also: landing day and time, days to evaluate, stay length, priorities, destination, crew and rover mobility, landing rules. | Builds `Requirements` |
| 02 AI agents | The seven LangGraph nodes and the conditional navigation branch | `POST /mission/plan` or `/mission/replan` |
| 03 Moon explorer | 3D terrain (orbit, zoom, pan, colour by elevation or slope, vertical exaggeration), 2D polar chart, search by name, ID or lat/lon, click to inspect, planner sites, surveyed sites, rover routes, LUNA WALK | Plan response; Person 3 grid and `/routes` |
| 04 Landing site | Recommended site and window, sunlight, Earth contact, blackout, slope, score, why it won and the trade-offs, per-day sunlight and Earth timeline, alternatives, rejected options, safety verdict, provenance, baseline comparison | Plan response, `/mission/compare` |
| 05 Safety simulation | Landing zone, rover deployment, destination, sample point, return. Rover and astronaut routes; energy, time, daylight and contact checks; five hazard scenarios; reroutes with recalculated distance, energy and time; GO, GO WITH CONDITIONS, or NO-GO: STOP OR REASSESS | See below |

## How the safety simulation is honest

- **Measurements** come only from the backend plan: sunlight hours, Earth-visible hours and longest blackout for the chosen site and day. The visibility service gives totals, not hour-by-hour timing, and the UI says that.
- **Terrain** is NASA LOLA (badged *NASA LOLA data*) when the grid file is present, otherwise Person 3's SYNTHETIC fixture (badged *Mock data*).
- **Routes** come from a line-by-line browser port of Person 3's `pathfinding.ts` and `routeService.ts`, in `js/terrain.js`. It was checked against the live Person 3 API: same distances, slopes and waypoints. The port adds one thing: obstacle masks for the crater and ridge scenarios.
- **Vehicle and crew figures** (speed, battery, drive energy, solar, EVA limits) are planning assumptions. They are shown and can be edited in Mission 05, and they are not telemetry.
- **Battery** uses a leg-by-leg charge model: drive and systems draw minus solar, with recharge while parked at the sample point.
- **Hazard scenarios** are labelled as simulated events. If no route satisfies the limits, the verdict is NO-GO. The planner never relaxes your limits on its own.

## Visuals that are artistic, and labelled so

The cabin, the shader Moon, Earth, the star field and the fine surface texture in 3D are illustrative. 3D geometry is the terrain grid itself. LUNA WALK runs at true vertical scale and is marked "not a photograph".

## Files

`js/app.js` (flow and UI), `js/api.js` (both API clients), `js/cabin.js` (opening scene), `js/moon.js` (shader Moon), `js/gl3d.js` (WebGL terrain, orbit camera, LUNA WALK), `js/terrain.js` (terrain loader and Person 3 pathfinder port), `js/safety.js` (safety and continuity model), `js/explorer.js` (2D chart), `js/geo.js` (projection, identical to Person 3 `geo.ts`), `data/p3_terrain_fixture.json` and `data/p3_sites_fixture.json` (snapshots of Person 3's own responses).

## Not built yet (data the backend doesn't provide)

Real NASA LOLA or SPICE-backed terrain and illumination: Person 2 and Person 3 have the hooks, and the UI shows whatever status they report. Hour-by-hour sunlight and Earth-visibility timelines. Live agent progress events: the UI shows an honest request-level state until the response arrives. Rock-scale obstacles below the 500 m grid.
