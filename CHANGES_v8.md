# v8 changes: every member on real NASA challenge data, plus fixes

**Date:** 2026-11-15. **Base:** `LUNA_NAV_AI_MISSION_COMMAND_v7.zip`.

The NASA Space Apps *Lunar Landing Site Navigator* challenge lists these NASA resources:

* **JPL Horizons** (Sun and Earth positions)
* **LRO LOLA** topography (Quickmap and Moon Trek)

In v8, real mode (`scripts/start_real_nasa.ps1`) runs every member on that data:

| Member | Data in v8 real mode | v7 |
|---|---|---|
| 1 Landing sites | NASA LRO LOLA `LDEM_75S_240M` | same |
| 2 Sun/Earth visibility | Live **JPL Horizons** (offline fallback: NASA NAIF SPICE DE440). Horizon is computed from LOLA. | same |
| 3 Navigation | **NASA LRO LOLA `LDEM_75S_240M`**, ±80 km around the pole at native 240 m | synthetic fixture (MOCK) |
| 4 Planner | Rejects any MOCK input (`LUNA_REQUIRE_REAL=1`) | accepted MOCK |
| 5 UI | 3D terrain from LOLA (unchanged). The default mission now works in real mode. | 502 error |

## Changes

### Person 3: real NASA terrain

* **New `src/server/lolaTerrain.ts`.** It reads the PDS `.img`/`.lbl` pair and checks the label:
  * south polar
  * 16-bit LSB integers
  * 1737.4 km reference sphere

  It then crops the DEM into the existing `TerrainGrid`. The projection is identical to Person 3's own (south-polar stereographic, R = 1 737 400 m), so no other routing code changed.
* **`index.ts`** uses LOLA when `LUNA_P3_LOLA_PATH` is set. Otherwise it keeps the labelled MOCK fixture, so the tests are unchanged.
* **`/health`** reports the terrain's real `data_status` instead of a hardcoded `"MOCK"`.
* **New `tests/lola.test.ts`** (4 tests):
  * loads a REAL 240 m grid
  * one pixel matches the NASA file (1575 m)
  * Shackleton crater appears as a deep depression, which shows the map is not mirrored
  * a route over real terrain is labelled REAL

### Person 1

* `/health` reports `REAL` and the DEM name when the NASA DEM is configured. Otherwise it reports `MOCK`. It used to always return `"UNAVAILABLE"`.

### Person 4 (planner)

* **Navigation fail-fast.** If navigation is required but no target is set, the planner returns 422 immediately with a clear message. Before, it computed visibility for about 150 s and then returned a 502.
* **No route is not a failure.** Person 3 `422 NO_ROUTE_FOUND` or `OUT_OF_COVERAGE` now marks that one site "route inaccessible". Before, it failed the whole mission with a 502. On real terrain, sites behind Shackleton's walls really are unreachable.
* **Concurrent visibility calls.** Visibility analyses now run 4 at a time (`LUNA_VISIBILITY_CONCURRENCY`, where 1 restores sequential calls). Result order is unchanged. Person 2's endpoint runs in a thread pool and its SPICE and LOLA code is already lock-protected.
  * The UI's default mission (6 sites × 3 days × 96 h, with navigation), cold cache: **290 s → 41–48 s**.
* **`LUNA_REQUIRE_REAL=1`.** Any MOCK input makes that option infeasible, whatever the request says.
* **Limitations name the MOCK inputs.** The text now lists exactly which inputs were MOCK (site, visibility or route). It no longer says "mock mode" when only the route was mock.
* **Fixed `tests/test_system.py`.** The wrapper now detects async nodes with `inspect.iscoroutinefunction`. This was the v6/v7 failing test.
* **New tests:**
  * `tests/test_real_mode.py` (4)
  * 2 Person 3 no-route contract tests in `tests/test_member3_contract.py`

### Scripts and UI

* **`start_real_nasa.ps1`:**
  * points Person 3 at the LOLA DEM
  * sets the traverse target to the geographic south pole on Shackleton's rim. Change it with `-NavTargetLat`/`-NavTargetLon`.
  * sets `LUNA_REQUIRE_REAL=1`
* **`start_integrated.ps1`:** falls back to `npx tsx` when `pnpm` is not installed.
* **`frontend/index.html`:** the default maximum traverse is 80 km, up from 10 km. Real LOLA routes from the candidate sites to the pole are 7–66 km.

## Verified results (2026-11-15)

* **Person 4:** 28/28 passed on 3 consecutive runs (the occasional Windows TestClient segfault is a known machine issue).
* **Person 1:** 10/10.
* **Person 2:** 134/134 with real SPICE and LOLA data.
* **Person 3:** 34/34, `tsc` clean.
* **Live full stack via `start_real_nasa.ps1`:** 25/25. Highlights:
  * Sun and Earth angles agree with a direct JPL Horizons query within 3.2e-5°.
  * Person 1 elevations equal a direct LOLA read (0 m difference).
  * Person 3 and Person 1 agree on site elevations within 26 m (bilinear vs. pixel sampling).
  * Navigation plans have **zero MOCK** inputs. Routes are labelled "NASA LRO LOLA LDEM_75S_240M (REAL)".
* **Browser, the UI's default mission as a judge would click it:**
  * HTTP 200 in 47.8 s, all 7 agents confirmed, 18 of 18 options feasible.
  * Recommendation: "Shackleton rim, 10.5 km from centre" (89.779°S, 155.73°W), 96 of 96 h of sunlight, Earth in view 96 of 96 h, slope 2.4°, LOLA traverse 7.5 km.
  * Runner-up: the connecting ridge.
  * In v7, the same click gave a 502 after about 150 s.

## Limits that remain

* REAL results stay **UNVERIFIED**: they come from NASA data but have not been independently reviewed, and they are not flight decisions.
* 240 m pixels hide boulders and small craters. Routes are slope-only and `operational_validity=NOT_VALIDATED`.
* Person 3's `/sites` demo list is still fixture sites labelled MOCK. The planner does not use it.
