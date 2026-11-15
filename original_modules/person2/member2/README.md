# visibility_planner: LUNA NAV AI Member 02 (Solar & Earth Visibility Planner)

For a site on the Moon and a mission interval, this module computes the **Sun and Earth azimuth/elevation** over time and the **windows** of sunlight, darkness, Earth visibility (direct-to-Earth radio line of sight) and loss of contact. It reports both **geometric** visibility (smooth sphere) and **terrain** visibility (above a local horizon profile).

**Data: NASA only, nothing to download.** By default (`engine: "auto"`) every number comes live from the **NASA/JPL Horizons API** (`https://ssd.jpl.nasa.gov/api/horizons.api`), the ephemeris tool listed in the Space Apps challenge resources. If the internet drops, the same computation runs offline from NASA NAIF SPICE kernels. The two engines agree to < 0.0002°.

**Real terrain:** `"horizon_profile_id": "lola"` computes each site's actual horizon from **NASA LRO LOLA `LDEM_75S_240M`** (240 m/pixel south-polar elevation grid, 29 MB, downloaded once). It reproduces Shackleton's permanently shadowed floor (0% sunlight) and the about 80% annual sunlight of the connecting ridge.

* Integration contract: **[API_CONTRACT.md](API_CONTRACT.md)**
* Start here if you are another team member: **[NEXT_MEMBER_START_HERE.md](NEXT_MEMBER_START_HERE.md)**
* Tests and accuracy: [TEST_REPORT.md](TEST_REPORT.md) · Data sources: [data/DATA_MANIFEST.md](data/DATA_MANIFEST.md)

## Space concepts in one line each

* **SPICE / kernels**: NASA's geometry toolkit and its data files (time, constants, orientation, and positions of bodies over time).
* **Ephemeris (DE440s)**: JPL's table of where the Sun, Earth and Moon are at any moment.
* **MOON_ME frame**: Moon-fixed axes (z = spin pole, x = mean direction to Earth). Lunar maps use the same latitude/longitude grid.
* **Azimuth / elevation**: compass direction (clockwise from north) and angle above the horizon.
* **Aberration correction LT+S**: we see the Sun where it was about 8 minutes ago (light time), slightly shifted by our own motion (stellar aberration).
* **Lunar day**: one sunrise to the next takes about 29.5 Earth days. Near the south pole the Sun just skims the horizon.
* **Horizon profile**: how high the surrounding terrain rises in each direction. A crater rim can hide a Sun that is above 0°.

## Install

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

On macOS/Linux, activate with `source .venv/bin/activate`. That is all you need for the default engine (live NASA/JPL Horizons API).

Optional, for the offline `spice` engine or the `auto` fallback (downloads about 44 MB into `data/spice_kernels/`):

```bash
python scripts/fetch_kernels.py
```

Optional, so the real-terrain grid is ready before the first request (otherwise it downloads on first use, 29 MB):

```bash
python scripts/fetch_lola.py
```

## Use

CLI. Print the full JSON:

```bash
python -m visibility_planner --lat -86 --lon 0 --start 2026-11-15T00:00:00Z --days 7 --step-min 10
```

CLI with a horizon profile, writing the result to a file and printing the summary:

```bash
python -m visibility_planner --lat -86 --lon 0 --start 2026-11-15T00:00:00Z --days 7 --horizon tests/fixtures/horizon_ridge.json --out result.json
```

CLI from a request file:

```bash
python -m visibility_planner --request examples/scenario_1.json --out examples/output/scenario_1.json
```

REST API (Swagger UI at `http://127.0.0.1:8002/docs`):

```bash
uvicorn visibility_planner.api:app --host 127.0.0.1 --port 8002
```

Python:

```python
from visibility_planner import analyze_site, compare_windows
res = analyze_site({"site": {"lat_deg": -86, "lon_deg_east": 0},
                    "start_utc": "2026-11-15T00:00:00Z", "duration_days": 7})
print(res.summary)
```

Plots of all three scenarios (written to `examples/output/*.png`):

```bash
python examples/plot_visibility.py
```

Tests:

```bash
python -m pytest -q
```

## Output (short)

You get `summary` (visible fractions, longest dark / no-contact stretch in hours), `windows` (`body` sun|earth|dark|no_contact, `kind` geometric|terrain, start/end UTC), `time_series` (az/el per step), `assumptions`, `uncertainty`, `kernels`, and `data_status`. The full field list and examples are in [API_CONTRACT.md](API_CONTRACT.md).
`data_status` is `REAL` for geometric-only results or a REAL horizon, `PARTIAL` when the horizon profile is synthetic (MOCK), and `MOCK` for the example payloads.

## Layout

```
visibility_planner/   sources.py (Horizons API + SPICE engines) lola.py + terrain.py (NASA LOLA horizons)
                      kernels.py frames.py ephemeris.py horizon.py
                      windows.py planner.py models.py cli.py api.py
                      mock_data/ (labelled MOCK responses served by /mock and use_mock)
schemas/              JSON Schemas generated from models.py
scripts/              fetch_kernels.py, fetch_horizons_reference.py, generate_fixtures.py
tests/                134 tests; fixtures/ (Horizons reference, synthetic horizons)
examples/             scenario_1..3.json, plot_visibility.py, mock_*_response.json, output/
```

After changing `models.py` or horizon shapes, run `python scripts/generate_fixtures.py` (the contract tests fail until you do).

## Assumptions and limitations

* Spherical Moon, R = 1737.4 km. Real topography enters only through a horizon profile.
* Planetocentric latitude (south negative), east-positive longitude, MOON_ME frame, degrees.
* No atmosphere or refraction. Sun and Earth are directions plus angular radius. Penumbra/partial illumination and Earth phase are not modelled.
* Default `center` definition (matches Horizons). `upper_limb` counts a body as visible when any part of its disk is above the horizon.
* Window edges are refined to about 1 s, but a rise and set inside one sampling step are missed.
* The default engine needs internet access to `ssd.jpl.nasa.gov`. A 7-day request takes about 5 s (several API calls, cached in memory).
* `lola` horizons use a 240 m grid: near-site slopes are averaged over about 240 m and sharp peaks are smoothed, which tends to **underestimate** illumination at the very best-lit points by up to about 10 percentage points. Rays stop at 200 km.
* The synthetic profiles (`flat`, `ridge`, `crater_rim`) remain for tests/demos and are labelled MOCK.
* Spherical-horizon "Earth visible" means geometric line of sight only. Antenna pointing, link budget and DSN scheduling are out of scope.
