# DATA_MANIFEST.md: datasets used by visibility_planner (Member 02)

All data are NASA/JPL products. Accessed **2026-11-14** by `scripts/fetch_kernels.py` and `scripts/fetch_horizons_reference.py`.

## Primary source: NASA/JPL Horizons API (live, no download)

| Dataset | URL | Used for |
|---|---|---|
| NASA/JPL Horizons System, API v1.2 | https://ssd.jpl.nasa.gov/api/horizons.api (docs: https://ssd-api.jpl.nasa.gov/doc/horizons.html) | Default engine. Every analysis queries it live: observer ephemeris, `CENTER='coord@301'` (site on the Moon), quantities 4 (apparent az/el) and 13 (angular diameter), Moon MEAN_ME frame, airless. Listed in the Space Apps 2026 "Lunar Landing Site Navigator" challenge resources. |

Captured sample responses for offline parser tests: `tests/fixtures/horizons_api_sample_{sun,earth}.json` (2026-11-14).

## Terrain: NASA LRO LOLA south-polar elevation grid (in `data/lola/`)

| Dataset | URL | Size (bytes) | Provides |
|---|---|---|---|
| LRO LOLA GDR `LDEM_75S_240M` (PDS3, product V2.0, created 2017-06-15, LOLA team / NASA GSFC) | https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/data/lola_gdr/polar/img/ldem_75s_240m.img (+ `.lbl`) | 29,062,688 | Heights (m, int16 × 0.5) above the 1737.4 km sphere, 75° S to the pole, 240 m/pixel, polar stereographic, frame "MEAN EARTH/POLAR AXIS OF DE421". Used to compute REAL horizon profiles. |
| PDS map projection catalog `DSMAP_POLAR.CAT` | https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/catalog/dsmap_polar.cat | 4,211 | Polar stereographic pixel ↔ lat/lon equations (forward equations + text used; orientation verified against Shackleton, Shoemaker, Cabeus). |

Accessed 2026-11-14. The `.img` is git-ignored; `scripts/fetch_lola.py` re-downloads it (parallel, resumable). The `.lbl` is also kept in `tests/fixtures/`.

## Optional offline source: NASA NAIF SPICE generic kernels (in `data/spice_kernels/`)

| Kernel | URL | Size (bytes) | Provides |
|---|---|---|---|
| naif0012.tls | https://naif.jpl.nasa.gov/pub/naif/generic_kernels/lsk/naif0012.tls | 5,257 | Leap seconds (UTC ↔ TDB) |
| pck00011.tpc | https://naif.jpl.nasa.gov/pub/naif/generic_kernels/pck/pck00011.tpc | 131,226 | Planetary constants: Sun and Earth radii (apparent disk size) |
| moon_pa_de440_200625.bpc | https://naif.jpl.nasa.gov/pub/naif/generic_kernels/pck/moon_pa_de440_200625.bpc | 12,863,488 | High-accuracy lunar orientation (DE440 principal axes) |
| moon_de440_250416.tf | https://naif.jpl.nasa.gov/pub/naif/generic_kernels/fk/satellites/moon_de440_250416.tf | 19,478 | Lunar frame definitions: MOON_ME, MOON_PA |
| de440s.bsp | https://naif.jpl.nasa.gov/pub/naif/generic_kernels/spk/planets/de440s.bsp | 32,726,016 | Sun/Earth/Moon positions, 1849–2150 (DE440s) |

The binary kernels (`.bsp`, `.bpc`) are git-ignored because of their size. Re-download them with `python scripts/fetch_kernels.py`.
Verified after loading: frame `MOON_ME` resolves with `pxform("MOON_ME", "J2000", et)`, so the fallback `MOON_ME_DE440_ME421` was not needed.

## Independent validation reference

| Dataset | URL | File | Content |
|---|---|---|---|
| NASA/JPL Horizons API | https://ssd.jpl.nasa.gov/api/horizons.api | `tests/fixtures/horizons_reference.json` | Apparent Sun/Earth az/el from 3 south-polar sites (−86°/129.8°E, −86°/0°E, −89.9°/129.8°E), every 6 h, 2026-11-15 to 2026-11-22 (174 rows), MEAN_ME frame, airless |

## Synthetic data (NOT NASA data, labelled MOCK)

| File | Content |
|---|---|
| `tests/fixtures/horizon_flat.json`, `horizon_ridge.json`, `horizon_crater_rim.json` | Synthetic horizon profiles, `data_status: "MOCK"`, `source: "synthetic_fixture"`. Real profiles will come from Member 01 (LOLA). |
| `examples/mock_*_response.json` | Example API payloads relabelled `MOCK` (numbers copied from a real SPICE run) |
