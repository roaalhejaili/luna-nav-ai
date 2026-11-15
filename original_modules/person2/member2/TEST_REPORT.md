# TEST_REPORT.md: visibility_planner (Member 02)

Run on 2026-11-14 on Windows 11, Python 3.11.9, SpiceyPy 8.4.0 (CSPICE N0067), NumPy 2.4.6, Pydantic 2.14.3, FastAPI 0.162.7, pytest 9.2.0.

## 1.2 update: real NASA LOLA terrain + offline-safe default

```
python -m pytest -q
134 passed in 143.38s                # internet + SPICE kernels + LOLA grid (includes year-long runs)
```

Re-run after the doc update: 133 passed, 1 failed. `test_live_analyze_default_engine_uses_horizons_when_online` failed because Horizons took more than 15 s, so `auto` fell back to SPICE as designed. That test now skips with the reason when a fallback happens; a rerun passed (Horizons answered in 21 s).
Offline with no kernels and no LOLA grid: `85 passed, 49 skipped`.

**LOLA terrain validation** (`test_lola.py`, `test_terrain.py`, LOLA API tests):
* Geometry on analytic terrain with exact answers: the smooth-sphere dip from 2 m is −0.087°; a ring wall matches the closed-form angle within one sampling step; a mountain appears at the right azimuth; great-circle destinations are correct.
* Projection: the round trip pixel↔lat/lon is exact. Orientation matches the PDS catalog text (lon 0 up, 90° E right). Crater floors sit at their true longitudes, not the mirrored ones:

  | Crater | Height at true centre | At mirrored longitude |
  |---|---|---|
  | Shackleton | −2786 m | +676 m |
  | Shoemaker | −3936 m | −1250 m |
  | Cabeus | −3730 m | +1777 m |

  Shackleton is about 4 km deep from rim to floor, matching its known depth.
* Physics against published LOLA illumination studies (Bussey et al. 2010; Mazarico et al. 2011):
  * Shackleton floor: **0% sunlight** over 120 days (a known permanently shadowed region).
  * Connecting ridge (−89.45°, −137.3° E): **81.3%** sunlit over 2027 (upper limb), against the published ~80–90%.
  * Best of 24 sampled Shackleton-rim crest points: 71–73%. That's below the published ~80–90% best-rim values; expected with a 240 m grid (smoothed peaks) and coarse rim sampling. Not a tight validation.
* Ray-casting cost: about 0.15 s per site (360 azimuths × 1667 samples).

**Offline-safe default (`engine: "auto"`):** with Horizons unreachable (simulated), the CLI and the API still return results from local SPICE kernels, with `data_source.fallback_reason` set. Real outages also happened during this session (DNS failures); the live-network tests failed during those minutes and passed when connectivity returned.

## 1.1 runs (for reference)

```
python -m pytest -q
113 passed in 24.88s                 # internet (live NASA/JPL Horizons API) + kernels
LUNA_OFFLINE=1 LUNA_SPICE_KERNEL_DIR=<empty dir> python -m pytest -q
78 passed, 35 skipped in 0.64s       # no network, no kernels: live-API and SPICE tests skip with a reason
```

## 0. Default engine = live NASA/JPL Horizons API (added in 1.1)

Scenario 1 (7 days, 10-min step, ridge horizon) was run through both engines:
* Horizons: 4 API requests, about 5.5 s. SPICE: about 0.1 s.
* Time series: max |Δ| between engines = 1.0e-4°, which is the 4-decimal output rounding.
* All 7 windows have identical start/end UTC to the second, and every summary value is identical.

`test_horizons_source.py` (12 tests):
* Offline: parsing of captured real API responses (Sun and Earth), the error-text path, query parameters (east longitude 0..360, altitude in km, quantities 4,13, UT), angular radius from the angular diameter, and a simulated network failure.
* Live: the 3 golden values straight from the API, the default engine is Horizons with `data_source` filled and no kernels, Horizons vs SPICE equality (az/el ≤ 2e-4°, window edges ≤ 2 s), and an off-grid end time.

API/CLI tests added: Horizons unreachable → 503 `UPSTREAM_UNAVAILABLE` and CLI exit code 4; Horizons rejects a query → 502 `UPSTREAM_ERROR`; `engine: "auto"` falls back to SPICE with `fallback_reason` when offline; the sunset countdown matches the SPICE-found sunset (61.98 h); the default engine is `horizons`.

The single warning is a Starlette deprecation notice about `httpx` inside FastAPI's TestClient. It does not affect this code.

## 1. Accuracy against NASA/JPL Horizons (independent reference)

The reference is `tests/fixtures/horizons_reference.json`: 3 sites × {Sun, Earth} × 29 epochs (every 6 h, 2026-11-15 to 2026-11-22), 174 rows in total. Horizons was queried with an observer on the Moon in the MEAN_ME frame, R = 1737.4 km, apparent az/el of the body centre, airless.

| Body | Rows | max \|Δaz\| (deg) | mean \|Δaz\| | max \|Δel\| (deg) | mean \|Δel\| |
|---|---|---|---|---|---|
| Sun | 87 | 5.1e-7 | 2.5e-7 | 4.9e-7 | 2.5e-7 |
| Earth | 87 | 8.9e-7 | 4.0e-7 | 5.0e-7 | 2.7e-7 |

These differences are at the rounding limit of Horizons' 6-decimal output, which means the method is identical: `spkcpo`, frame `MOON_ME`, `LT+S` correction. With `LT` only or `NONE`, the azimuth error grows to about 0.006°, which shows the stellar-aberration term matters at this level.
Hand-checked golden values pass at the 0.05° tolerance, at 2026-11-15T00:00:00Z:
* −86.0°, 129.8°E Sun: az 344.5666, el 5.4128
* −86.0°, 0°E Earth: az 357.3841, el 0.4425
* −86.0°, 0°E Sun: az 114.4776, el −0.1001

**Verified against Horizons:** apparent az/el of Sun and Earth centres (the `center` definition) at the 3 reference sites over 7 days.
**Not verified against Horizons:** the `upper_limb` definition (it depends on our angular radius from PCK radii, which is only sanity-checked: Sun 0.26–0.28°, Earth 0.9–1.0°); window edge times (checked by bracketing with SPICE itself, not by an independent rise/set table); sites away from the south pole (the far-side and near-side equator checks are physical sanity checks, not reference comparisons); `alt_m ≠ 0`.

## 2. What each test file proves

| File | # | What it proves |
|---|---|---|
| `test_frames.py` | 15 | Topocentric basis is orthonormal and right-handed at 6 sites including near-poles. Zenith gives el 90; east, north, south and west give az 90/0/180/270 with el 0. The north = +z sign is correct at the equator. Vectorised az/el works. Altitude is in meters. |
| `test_windows.py` | 8 | Known sine crossings are found. Bisection refinement error is < 0.01 s at a 97 s step (much smaller than the step, and better than linear interpolation). Always-visible and never-visible cases work. Windows cut by the interval are flagged. A crossing on the first sample is not mis-flagged. Windows and gaps partition the interval exactly. Bad input is rejected. |
| `test_horizon.py` | 14 | Wrap-around interpolation from 359.9° to 0.1° works, including negative and >360° azimuths, and unsorted input. The synthetic shapes are correct (ridge 3° at N, rim 1–4° with a gap at 160°). The fixture files equal the generator output. Invalid profiles are rejected. A ridge blocks a body that is above 0° but below the ridge. Terrain visibility is ≤ geometric visibility. |
| `test_ephemeris.py` | 9 | The frame is MOON_ME. 3 hand-checked golden values and all 174 Horizons rows match. Angular radii are computed, not hardcoded. UTC↔ET round-trips. At 86°S the Sun's elevation changes < 0.1°/h. Earth range is about 380 000 km. |
| `test_planner.py` | 13 | Output validates against the Pydantic contract. Every timestamp is ISO with `Z`. The data_status rules hold (REAL / PARTIAL with MOCK horizon / REAL with a REAL horizon). Output is deterministic. Terrain ≤ geometric and flat = geometric. upper_limb ≥ center. A refined sunrise is bracketed within ±60 s by SPICE. Fractions agree with window durations. On the far side Earth is never visible; at the near-side centre it is always visible. Sunrise-to-sunrise at 86°S is 29–30.5 days (lunar day). Mission metadata is echoed. compare_windows output is consistent with analyze_site and contains no ranking. |
| `test_errors.py` | 9 | These are rejected: naive datetime, lat > 90 or < −90, end ≤ start, both/neither end and duration, too many samples, step 0, unknown fields, bad enum, two horizon inputs. Timezone offsets are converted to UTC and longitude is normalised. A missing kernel directory or files raise `KernelError` with a fix hint. Mock mode works without kernels. |
| `test_api.py` | 11 | `/health`, `/meta`, `/analyze`, `/compare`, `/horizon-profiles`, `/mock` and `/openapi.json` work. Validation errors (including malformed JSON and an unknown profile id) return the 422 envelope with field paths. Missing kernels return 503 `KERNELS_UNAVAILABLE`, health reports `degraded`, and `use_mock` still works. 404 envelope. |
| `test_cli_and_contract.py` | 15 | CLI flags, `--request` file plus overrides, `--horizon` file and `--no-time-series` work. Exit codes are 2 for bad input and 3 for missing kernels. Published `schemas/*.json` equal the models. Mock files are valid, labelled MOCK, and identical in package and `examples/`. Scenario files are valid requests. |

## 3. Manual verification (also run on 2026-11-14)

* `python examples/plot_visibility.py` produced 3 PNGs in `examples/output/`. In scenario 1 the Sun stays within 0–5° of the horizon, rising about 0.03°/h. Earth stays low, near az 355°, between 0.4° and 9.3°. The ridge horizon hides the Earth for the first 45.6 h.
* A 59-day run at −86°, 0°E gives sunrises at 2026-11-15T03:05:24Z and 2026-12-14T22:59:29Z, 29.8 days apart, matching a lunar day.
* A live `uvicorn` server was tested with curl: health OK, scenario 2 analysis (1009 samples), 422 envelope, and CORS preflight 200.

## 4. Uncertainty summary

| Source | Size / effect |
|---|---|
| Ephemeris + Moon orientation (DE440s, MOON_ME) | < 1e-6° versus Horizons (same underlying model; this is not absolute truth) |
| Spherical Moon | No local topography unless a horizon profile is given. At 86°S real terrain of a few degrees changes visibility strongly (see the terrain fractions). |
| Sampling + refinement | Edges refined to about 1 s. Events shorter than one step (a rise and set inside one step) can be missed, so use a smaller `step_minutes` for grazing geometry. |
| Sun as a point / `upper_limb` | Penumbra and partial illumination are not modelled. The Sun's disk is about 0.27° wide, so near 86°S the difference between centre and limb crossing is roughly 9 h. |
| Refraction | None (airless). |
| Horizon profiles | All current profiles are synthetic MOCK data. Terrain results are illustrative until Member 01 delivers LOLA-derived profiles. |

## 5. Tests that could not be run

None. All 113 tests ran, including the live NASA/JPL Horizons API tests (network available on 2026-11-14).
