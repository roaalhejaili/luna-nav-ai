# PROMPT FOR CLAUDE CODE: Member 02, Solar & Earth Visibility Planner (visibility_planner)

Paste everything below the line into Claude Code, started inside the folder that holds `scripts/`, `requirements.txt` and this file.

---

You are helping me build **Member 02: Solar & Earth Visibility Planner** (`visibility_planner`) for our NASA Space Apps 2026 project **LUNA NAV AI**, a lunar landing-site navigator (Moon only). I am an AI student with strong Python/ML skills but I have never done astronomy or SPICE. Explain each space concept in one or two plain sentences the first time you use it, then keep building.

## 0. Hard constraints
- **Time:** building is allowed from 14 Nov and our submission deadline is **11:59 pm Saudi time on 15 Nov 2026**. Work MVP-first: a correct, tested core first (section 4 items 1 to 4), polish after. Commit after every working milestone (`git init` if needed; never push).
- NASA data only. **Never invent astronomical numbers.** Every number comes from SPICE kernels. Anything synthetic (test horizon profiles) is labelled `data_status: "MOCK"` and `source: "synthetic_fixture"`.
- This module must run **standalone**: no dependency on the terrain module (Member 01), the AI supervisor (Member 04), the map (Member 03) or the dashboard (Member 05). Use fixed test locations and synthetic horizon profiles.
- Distances in km inside SPICE calls, but our public outputs use: UTC ISO-8601 strings, angles in degrees, elevation/heights in meters.
- Do not claim anything works unless you ran it. If a step cannot run in your shell, say so.

## 1. My assignment (from the team plan)
Module `visibility_planner`. Tools: Python, SpiceyPy, NASA SPICE, NumPy, Pytest.
1. Compute Sun and Earth **elevation and azimuth** as seen from a lunar surface location at given UTC times.
2. Find **windows** (start/end UTC) of Sun visibility, Earth visibility (= direct-to-Earth line of sight), darkness (Sun below horizon) and loss of direct contact (Earth below horizon) over the mission duration.
3. Use a local horizon profile from an independent fixture or data file, and clearly separate **geometric visibility** (smooth sphere horizon, elevation > 0) from **terrain-obstructed visibility** (elevation above the local horizon profile at that azimuth).
4. Compare two or more time windows; document kernels used, assumptions, time resolution and uncertainty.
Definition of done: a standalone **API or CLI** that returns a **time series + visibility windows**, plus a clear scientific test report. At least 3 tests (aim for 10+).

Shared team conventions: UTC ISO-8601, degrees, meters, explicit coordinate convention, and `data_status` in `REAL | MOCK | PARTIAL | UNAVAILABLE` (never show fake results as real). Mission input includes mission type, target, start date UTC, duration, power/contact constraints. Output must be consumable by the AI supervisor (Member 04) and the dashboard (Member 05) as JSON.

## 2. Setup (do these first, in order)
1. `python -m venv .venv` and activate it, then `pip install -r requirements.txt` (spiceypy, numpy, pydantic, pytest, matplotlib). Confirm `python -c "import spiceypy; print(spiceypy.tkvrsn('TOOLKIT'))"` works on this machine.
2. `python scripts/fetch_kernels.py` downloads ~44 MB of SPICE kernels into `data/spice_kernels/` and runs a smoke test. The NAIF server may be unreachable from some sandboxed shells; this runs on my own machine. If it fails, show me the error and stop. Do not fabricate kernels.
3. `python scripts/fetch_horizons_reference.py` writes `tests/fixtures/horizons_reference.json`, independent Sun/Earth az/el values from NASA/JPL Horizons used to validate our results.
4. Create a small `data/DATA_MANIFEST.md` listing every kernel (name, URL, size, date accessed, what it provides). The NASA Space Apps rules require dataset names, links and access dates in our submission.

Kernel set (all verified to exist on 2026-11-14):
| Kernel | Role |
|---|---|
| `naif0012.tls` | leap seconds, needed to convert UTC to ephemeris time |
| `pck00011.tpc` | body radii |
| `moon_pa_de440_200625.bpc` | high-accuracy Moon orientation from DE440 |
| `moon_de440_250416.tf` | defines lunar frames (`MOON_ME` mean-Earth/mean-rotation frame, `MOON_PA` principal axes) |
| `de440s.bsp` | positions of Sun, Earth, Moon (1849 to 2150) |
Load all of them with `spiceypy.furnsh`. After loading, verify `MOON_ME` resolves with `spiceypy.pxform("MOON_ME", "J2000", et)`. If that frame name is not defined by the 250416 frame kernel, report it and use the DE440 frame `MOON_ME_DE440_ME421` instead. Do not guess silently.

## 3. Physics and method (get these right)
- **Coordinates:** planetocentric latitude (south negative), **east-positive longitude**, degrees. Moon treated as a sphere of radius **1737.4 km** (matches Horizons). Site position vector in the Moon-fixed frame: `spiceypy.georec(lon_rad, lat_rad, alt_km, 1737.4, 0.0)`.
- **Topocentric frame at the site** (up/east/north): `up = r/|r|`, `east = (-sin lon, cos lon, 0)`, `north = up x east` (check the sign by testing at the equator). `elevation = asin(dot(d, up))`, `azimuth = atan2(dot(d, east), dot(d, north))` in 0..360 degrees measured **clockwise from north**.
- **Direction to target:** get the vector from the Moon-fixed site to the Sun and to the Earth in the `MOON_ME` frame. Preferred: `spiceypy.spkcpo` with the site as an observer on body MOON in frame MOON_ME, aberration correction `LT+S`. Alternative: `spkpos(target, et, "MOON_ME", "LT+S", "MOON")` minus the site vector. State which you used. Convert UTC strings with `spiceypy.str2et`.
- **Apparent size:** the Sun's angular radius is about 0.27 degrees and the **Earth's about 0.95 degrees** as seen from the Moon (compute from distance and radius, do not hardcode). Support two visibility definitions and record which is used in the output: `center` (center above horizon) and `upper_limb` (any part of the disk above the horizon; add the angular radius). Default: `center`, for consistency with Horizons.
- **Visibility rule:** body visible when `elevation_deg > horizon_elevation_deg(azimuth)`. For the geometric case the horizon elevation is 0. For terrain case use a horizon profile: a list of `(azimuth_deg, elevation_deg)` samples over 0..360 with wrap-around linear interpolation.
- **Windows:** sample at a configurable step (default 10 minutes), then locate each rise/set crossing by linear interpolation or bisection between samples so window edges are better than the step. Return windows as `{body, kind: "geometric"|"terrain", start_utc, end_utc, duration_hours}`. Handle windows that start before or run past the mission interval, and the "always visible / never visible" cases (no crossings). Near the poles the Sun skims the horizon and elevation changes by only about 0.02 deg per hour at 86 S, so test the polar cases carefully.
- **Unobstructed vs obstructed:** report both, plus fractions: `sun_visible_fraction`, `earth_visible_fraction` for geometric and terrain cases, and the longest continuous dark period and longest continuous loss-of-contact period.
- **Uncertainty (document in the output and README, do not make up numbers):** sampling step and interpolation; kernel set and Moon orientation model; spherical Moon (no real topography at the site unless a horizon profile is supplied); no atmosphere or refraction on the Moon; the Sun treated as a disk (penumbra/partial illumination is not modelled); a supplied horizon profile is only as good as its source. Quantify what you can by comparing against Horizons (section 5).

## 4. Build this
```
visibility_planner/
  __init__.py
  kernels.py       load_kernels(kernel_dir) (idempotent), kernel manifest, clear error if a file is missing
  frames.py        site_vector, topocentric basis, to_az_el
  ephemeris.py     sun_earth_az_el(site, times_utc) -> arrays of az/el/range
  horizon.py       HorizonProfile (interp, wrap-around), flat_horizon(), synthetic profiles
  windows.py       find_windows(times, elevation, horizon_el) with refined crossings
  planner.py       analyze_site(request) -> VisibilityResult ; compare_windows(...)
  models.py        Pydantic v2 models: SiteInput, MissionWindow, TimeSeriesPoint, VisibilityWindow, VisibilityResult
  cli.py           python -m visibility_planner --lat -86 --lon 0 --start 2026-11-15T00:00:00Z --days 7 --step-min 10 [--horizon file.json] [--out result.json]
tests/
  fixtures/horizon_flat.json, horizon_ridge.json, horizon_crater_rim.json   (synthetic, data_status MOCK)
  fixtures/horizons_reference.json  (from scripts/fetch_horizons_reference.py)
  test_*.py
examples/
  scenario_1.json, scenario_2.json, scenario_3.json   (three 7-day science missions near the south pole, different start dates and sites)
  plot_visibility.py  (matplotlib: elevation time series with horizon line and shaded windows)
README.md  TEST_REPORT.md  DATA_MANIFEST.md
```
1. **Core ephemeris** (`frames.py`, `ephemeris.py`): vectorised where practical (NumPy), SPICE called per time in a loop is fine for a few thousand samples.
2. **Windows** (`windows.py`): described above; pure NumPy, fully unit-testable without SPICE.
3. **Horizon support** (`horizon.py`): JSON format `{"site_id": "...", "data_status": "MOCK", "source": "synthetic_fixture", "azimuth_deg": [...], "elevation_deg": [...]}`. Provide 3 synthetic profiles: flat (0 deg), a ridge of about 3 deg centered on north with a smooth shape, and a crater-rim style profile of about 1 to 4 deg all around with one gap. Document that real horizons come later from Member 01's terrain data.
4. **Public API and CLI** (`planner.py`, `cli.py`): produce the JSON contract below. Validate with Pydantic. Exit with a clear message on bad input (latitude out of range, naive datetime, missing kernels).
5. **Compare windows**: `compare_windows(site, [window_a, window_b])` returns per-window fractions, longest dark/no-contact stretch and a side-by-side summary that Member 04 can rank. Do not rank or recommend; just report numbers.
6. **Scenarios and plot**: three scenario JSON files and the plot script; save PNGs under `examples/output/`.

### JSON output contract (keep stable; other members mock this exactly)
```json
{
  "site_id": "site_A", "body_frame": "MOON_ME", "moon_radius_km": 1737.4,
  "location": {"lat_deg": -86.0, "lon_deg_east": 0.0, "alt_m": 0.0},
  "start_utc": "2026-11-15T00:00:00Z", "end_utc": "2026-11-22T00:00:00Z", "step_minutes": 10,
  "visibility_definition": "center",
  "horizon": {"type": "geometric|terrain", "profile_id": null, "data_status": "REAL|MOCK", "source": "..."},
  "summary": {
    "sun_visible_fraction": 0.0, "earth_visible_fraction": 0.0,
    "sun_visible_fraction_terrain": null, "earth_visible_fraction_terrain": null,
    "longest_dark_hours": 0.0, "longest_no_contact_hours": 0.0
  },
  "windows": [{"body": "sun|earth|dark|no_contact", "kind": "geometric|terrain", "start_utc": "...", "end_utc": "...", "duration_hours": 0.0}],
  "time_series": [{"utc": "...", "sun_az_deg": 0.0, "sun_el_deg": 0.0, "earth_az_deg": 0.0, "earth_el_deg": 0.0, "sun_visible": true, "earth_visible": true}],
  "assumptions": ["..."], "kernels": [{"name": "...", "role": "..."}],
  "data_status": "REAL", "source": "NASA NAIF SPICE (DE440s, MOON_ME)"
}
```
`data_status` is `REAL` only when computed from real kernels with a geometric horizon; when a synthetic horizon profile is used, the terrain part is `MOCK` and the top-level status is `PARTIAL`.

## 5. Tests (pytest, aim for 12+; mark kernel-dependent tests `needs_kernels`)
- **Golden values from Horizons (verified by hand on 2026-11-14), tolerance 0.05 deg in azimuth and elevation (looser for azimuth at latitudes beyond 89.5 S):**
  - Site lat -86.0, lon 129.8 E, 2026-11-15T00:00:00Z: **Sun az 344.5666, el 5.4128**
  - Site lat -86.0, lon 0.0 E, 2026-11-15T00:00:00Z: **Earth az 357.3841, el 0.4425**; **Sun az 114.4776, el -0.1001**
  - Also compare every row of `tests/fixtures/horizons_reference.json` (3 sites, Sun and Earth, every 6 h for 7 days).
- Geometry unit tests without SPICE: topocentric basis orthonormal; a target straight up gives el = 90; due east gives az = 90; a point on the horizon gives el = 0.
- Windows: synthetic sine elevation with known crossings; always-visible; never-visible; window cut by the interval edges; refinement error smaller than the step.
- Horizon: wrap-around interpolation at 359.9 to 0.1 degrees; a ridge that blocks the Sun when it is below the ridge elevation but above 0 (terrain visibility less than or equal to geometric visibility, always).
- Contract: output validates against the Pydantic model, ISO-8601 UTC with `Z`, `data_status` rules, deterministic output for the same inputs.
- Error handling: naive datetime, lat > 90, missing kernel directory.
Run `pytest -q` and report the counts. Write `TEST_REPORT.md` with what each test proves, the measured differences from Horizons (max and mean, in degrees), and any test you could not run.

## 6. Quality bar
Type hints everywhere, small functions, docstrings that state units, no global state except the kernel loader, no hardcoded absolute paths, no secrets. `README.md` covers install, fetching kernels, CLI examples, the JSON contract, assumptions and limitations (section 3), and how Members 04 and 05 call it (`python -m visibility_planner ... --out result.json`, or `from visibility_planner import analyze_site`). Also provide `examples/mock_visibility_response.json` (clearly labelled `MOCK`) exactly matching the contract so the other members can build against it today.

## 7. Verification before you report done
1. `pytest -q` passes; show the output.
2. Run the CLI for scenario 1 and show the summary block.
3. Run the plot script and view one PNG; confirm the Sun curve is sensible (near the south pole the Sun stays within a few degrees of the horizon and moves through a full lunar day of about 29.5 Earth days; Earth stays low and nearly stationary from near-side sites, and is never visible from the far side).
4. State clearly what is verified against Horizons and what is not.

Start by listing your plan in 8 lines or fewer, then run setup (section 2), then build.
