# DATA_SOURCES_MEMBER2.md: what Member 02 uses (verified 2026-11-14)

## Short version
You do not need any big image or elevation files. You need **SPICE kernels** (about 44 MB, from NASA NAIF) and the **SpiceyPy** Python library. Terrain/horizon data from Member 01 is not needed yet: the plan says to use synthetic horizon profiles until integration.

## SPICE kernels (all existence and sizes confirmed on the NAIF server)
Base URL: `https://naif.jpl.nasa.gov/pub/naif/generic_kernels/`
| File | Folder | Size | Provides |
|---|---|---|---|
| naif0012.tls | lsk/ | 0.01 MB | leap seconds |
| pck00011.tpc | pck/ | 0.13 MB | body radii |
| moon_pa_de440_200625.bpc | pck/ | 12.27 MB | Moon orientation (DE440) |
| moon_de440_250416.tf | fk/satellites/ | 0.02 MB | lunar frames MOON_ME / MOON_PA |
| de440s.bsp | spk/planets/ | 31.21 MB | Sun, Earth, Moon positions 1849 to 2150 |
Note: `moon_de440_220930.tf` (which I first guessed) is an older version, now in `fk/satellites/a_old_versions/`. The current one is `moon_de440_250416.tf`.
The tool `scripts/fetch_kernels.py` downloads all five and runs a smoke test.

## Independent reference for validation
NASA/JPL Horizons API: `https://ssd.jpl.nasa.gov/api/horizons.api` (observer on the Moon via `CENTER='coord@301'` plus `SITE_COORD`; Moon frame MEAN_ME high precision; airless). Verified working. Sample values checked by hand are listed in the Claude Code prompt as golden tests. `scripts/fetch_horizons_reference.py` pulls a 7-day table for 3 sites.

## Library
`spiceypy` (installed OK in a test environment: SpiceyPy 8.4.0 with CSPICE N0067, NumPy 2.5.4, pytest 9.2.0). PyPI is reachable; NAIF is not reachable from some sandboxed shells, so run the fetch scripts on your own machine.

## Rules from the Participant Guide (Space Apps Saudi Arabia 2026)
- Build during 14-15 Nov only; **submit before 11:59 pm Saudi time on 15 Nov**.
- Record every dataset: name, link, date accessed (goes into the References field). Use `data/DATA_MANIFEST.md`.
- Your project must use NASA data to be eligible for global awards: SPICE and Horizons are NASA/JPL data.
