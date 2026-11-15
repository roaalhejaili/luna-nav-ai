# LUNA NAV AI: Lunar Landing Site Navigator (final version)

NASA Space Apps Challenge 2026: *Lunar Landing Site Navigator*.

LUNA NAV AI chooses **where and when to land near the lunar south pole**, using the NASA data that the challenge points to:

| Part | What it does | NASA data |
|---|---|---|
| Person 1, sites | Finds flat, high candidate landing sites | **LRO LOLA LDEM_75S_240M** (240 m south-polar elevation map) |
| Person 2, Sun and Earth | Sun and Earth above the local horizon, hour by hour: power and direct-to-Earth contact | **Live NASA/JPL Horizons** (offline fallback: **NASA NAIF SPICE DE440**). Horizon from LOLA terrain. |
| Person 3, navigation | Rover routes that respect a slope limit | **LRO LOLA LDEM_75S_240M** |
| Person 4, planner | 7-step LangGraph agent pipeline. Ranks options with Pareto layers and MILP selection. | Uses the three above |
| Person 5, app | Mission Command web app: 3D Moon, agents, landing site, safety simulation | LOLA terrain for 3D |

All NASA data files are **included in this zip** (about 73 MB, checked by SHA-256 in `DATA_CHECKSUMS.txt`).

## Run it on Windows (3 steps)

1. **Install once:**
   * [Python 3.11+](https://www.python.org/downloads/): tick *"Add python.exe to PATH"*.
   * [Node.js LTS](https://nodejs.org/).
2. **Extract the zip first.** Right-click `LUNA_NAV_AI_FINAL.zip`, choose **Extract All…**, and open the extracted `LUNA_NAV_AI_FINAL` folder. Running the `.bat` files from inside the zip does not work.
3. Double-click **`RUN.bat`**.
   * The first time, it installs everything automatically. That takes about 3–5 minutes and needs internet.
   * Then it starts all the services and opens the app at **http://localhost:5173**.
   * Click **START MISSION**, then **Launch mission analysis**.

The `localhost:5173` link only works while `RUN.bat` is running. A black backend window stays open; keep it open.

* The first mission takes about **45 s**, because it calls JPL Horizons live. Repeats are faster.
* Internet is needed for live JPL Horizons. Without it, Person 2 automatically uses the bundled NASA SPICE kernels.
* To finish, double-click **`STOP.bat`**.
* To check everything, double-click **`TEST.bat`**. It runs the unit tests of all members. If `RUN.bat` is running, it also runs the 25 live NASA API tests.

## Other systems (macOS / Linux)

Steps 1–3 are the same idea, but run these by hand from this folder:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r original_modules/person1/requirements.txt -r original_modules/person2/member2/requirements.txt
(cd original_modules/person3/moon_navigation && npm ci)
```

Then use the same environment variables as `scripts/start_real_nasa.ps1`, and serve `frontend/` on port 5173.

## Expected results (measured 2026-11-15)

| Suite | Result |
|---|---|
| Live NASA API, full stack, "no MOCK anywhere" | **25 / 25** |
| Person 4 planner | 28 / 28 |
| Person 1 sites | 10 / 10 |
| Person 2 visibility, real NASA data | 134 / 134 |
| Person 3 navigation | 34 / 34 |

Independent checks against NASA:

* Sun and Earth angles agree with a direct JPL Horizons query within **0.00003°**.
* Site elevations equal a direct read of the LOLA file (**0 m** difference).
* SPICE and Horizons agree.

## Honest limits (say these to judges)

* Results are labelled **UNVERIFIED**: they are computed from NASA data, but no independent review has checked them. They are not flight decisions.
* 240 m pixels cannot show boulders or small craters. Routes are slope-only (`operational_validity = NOT_VALIDATED`).
* Every agent step is deterministic. An LLM is used only if you set `GEMINI_API_KEY`, and only for wording, never for numbers.

Details: `CHANGES_v8.md` (what changed), `README.md`, `ARCHITECTURE.md` and `API_CONTRACT.md`.
