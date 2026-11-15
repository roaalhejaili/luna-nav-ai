# LUNA NAV AI: Lunar Landing Site Navigator

**NASA Space Apps Challenge 2026 · Challenge: [Lunar Landing Site Navigator](https://www.spaceappschallenge.org/2026/challenges/lunar-landing-site-navigator/)**
**Team LUNA NAV AI · Madinah, Saudi Arabia**

## Summary

Missions to the lunar south pole must land where the Sun can power them and where Earth stays in view for direct communication. Both depend on terrain, location and date, and they change quickly near the pole.

LUNA NAV AI is a mission-planning web app. A planner picks a mission type and landing dates. The app then:

* finds candidate landing sites on NASA LRO LOLA terrain
* computes the Sun's and Earth's elevation above each site's real local horizon, from NASA/JPL Horizons
* checks rover routes over the same LOLA terrain
* ranks every site-and-date option against the mission's rules, and explains its choice

When dates or requirements change, it replans in seconds. This is the situation the challenge describes, where schedules slip and teams need alternatives fast.

## How to run (Windows)

1. Install [Python 3.11+](https://www.python.org/downloads/) (tick *Add to PATH*) and [Node.js LTS](https://nodejs.org/).
2. Extract the zip, open the folder, and double-click **`RUN.bat`**.
   * The first run installs everything (about 3–5 minutes, needs internet).
   * Then it opens **http://localhost:5173**.
3. Click **START MISSION**, then **Launch mission analysis**. The first plan takes about 40 s.

| Other launchers | What they do |
|---|---|
| `STOP.bat` | Stops everything |
| `TEST.bat` | Runs all the tests |

The NASA data files are bundled and checked against `DATA_CHECKSUMS.txt`. See `START_HERE.md` for macOS/Linux.

## NASA data used

| Dataset | Source | Used for |
|---|---|---|
| **LRO LOLA `LDEM_75S_240M`**: south-polar elevation map, 240 m/pixel | NASA PDS Geosciences Node ([archive](https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/data/lola_gdr/polar/img/)) | Candidate sites, elevation and slope (Person 1); the terrain horizon for each site (Person 2); rover routes (Person 3); the 3D Moon in the app (Person 5) |
| **JPL Horizons System**: live ephemeris API | NASA/JPL Solar System Dynamics ([ssd.jpl.nasa.gov/horizons](https://ssd.jpl.nasa.gov/horizons/)) | Sun and Earth azimuth and elevation from each lunar site, hour by hour (Person 2) |
| **NAIF SPICE kernels**: `de440s.bsp`, `moon_pa_de440_200625.bpc`, `moon_de440_250416.tf`, `pck00011.tpc`, `naif0012.tls` | NASA NAIF ([naif.jpl.nasa.gov](https://naif.jpl.nasa.gov/pub/naif/generic_kernels/)) | Offline fallback for the same Sun/Earth geometry, and the Moon's Mean-Earth body frame |

The challenge also lists **Quickmap** (ASU/LROC) and **Moon Trek** (NASA/JPL). Both are viewers of the same LRO LOLA data. We consulted them to understand the terrain and used the raw LOLA archive in code, because neither viewer offers numeric elevation data that code can read.

## How it works

```
Mission request ─► 1 Supervisor ─► 2 Site analysis ─► 3 Sun & Earth visibility ─► 4 Navigation (if required)
   (web app)          (LangGraph)      LOLA terrain        JPL Horizons + LOLA horizon     LOLA routes (A*)
                                                                    │
            7 Explanation ◄─ 6 Optimization ◄─ 5 Scientific validation ◄┘
            evidence-only text   Pareto layers + MILP     hard constraints + data provenance
```

* **Persons 1–3** are independent REST services, each owning one NASA calculation. **Person 4** coordinates them with a 7-step LangGraph pipeline. **Person 5** is the Mission Command web app.
* Every number comes from NASA data and deterministic code.
* Each result carries its data source. Values computed from NASA data are labelled **UNVERIFIED**: NASA-derived, but not independently reviewed. Real mode refuses any MOCK input.

## Verified results (2026-11-15, full stack on NASA data)

| Check | Result |
|---|---|
| Live API tests: all services running, zero MOCK inputs | **25 / 25** |
| Unit tests: Person 4 / 1 / 2 / 3 | 28 / 10 / 134 / 34 passed |
| Sun and Earth elevation vs. a separate direct JPL Horizons query | max difference **0.00003°** |
| Site elevations vs. a direct read of the LOLA file | **0 m** difference |
| Offline SPICE vs. live Horizons, 49 samples | agree |

* **Default mission:** 6 sites × 3 days × 96 h. The recommendation is the **rim of Shackleton crater** (89.78°S, 155.73°W): sunlight 96 of 96 h, Earth in view 96 of 96 h, slope 2.4°, LOLA rover traverse 7.5 km.
* **Runner-up:** the Shackleton connecting ridge.

## Use of AI

* **In the product:**
  * The planning pipeline is LangGraph code. Its steps are deterministic and compute nothing with an LLM.
  * Google **Gemini** is optional (only when `GEMINI_API_KEY` is set). It does two language tasks: it classifies the free-text mission request, and it writes a short summary of the chosen site.
  * A checker rejects any Gemini text containing a number that is not in the computed evidence.
  * All submitted results were produced with Gemini off (0 LLM calls).
* **In development:** the team used AI coding assistants, including Anthropic **Claude** (Claude Code), to write code, review it, test it and document it. Every result above was measured by running the code, not generated by AI.

## Limits

* Results are planning estimates, not flight decisions.
* 240 m pixels cannot show boulders or small craters.
* Routes check slope only (`operational_validity = NOT_VALIDATED`).

## Team

| Member | Role |
|---|---|
| Shahad Tahir | Member 1: terrain and landing sites |
| Roaa Alhejaili | Member 2: Sun and Earth visibility |
| Aseel Aldhahri | Member 3: navigation |
| Juri Almarwani (team leader) | Member 4: multi-agent AI planner |
| Abdualrhman Algharbani | Member 5: frontend |

## References

**NASA data and tools**

* NASA PDS Geosciences Node, *LRO LOLA Gridded Data Records*, `LDEM_75S_240M`.
* NASA/JPL Solar System Dynamics, *Horizons System* and Horizons API.
* NASA NAIF, *SPICE generic kernels*.
* ASU LROC *QuickMap*; NASA/JPL *Moon Trek*. Consulted for visual context.
* NASA Space Apps 2026, *Lunar Landing Site Navigator* challenge and resources.

**Open-source software**

* Python: FastAPI, Uvicorn, Pydantic, httpx, LangGraph, SciPy (MILP), NumPy, SpiceyPy (NAIF CSPICE), Matplotlib, pytest, truststore.
* JavaScript/TypeScript: Node.js, Express, React, Vite, Vitest, OpenLayers, proj4, zod, tsx, supertest.

**AI services**

* Google Gemini API (optional, language only).
* Anthropic Claude / Claude Code (development assistant).

Developer documentation: `START_HERE.md`, `ARCHITECTURE.md`, `API_CONTRACT.md`, `CHANGES_v8.md`, `PERSON4_README.md`, and each member's folder under `original_modules/`.
