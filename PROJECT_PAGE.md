# Space Apps project page: text to paste

Copy each section into the matching field on the Space Apps project page. Replace `<LINK>` with your public GitHub or Google Drive link.

---

## Project name
LUNA NAV AI

## High-level summary

LUNA NAV AI is a mission-planning web app for the lunar south pole. It answers the challenge's core question: *where and when should we land so the Sun powers us and Earth stays in view?*

A planner picks a mission and dates. The app then:

* finds candidate sites on **NASA LRO LOLA** terrain
* computes Sun and Earth elevation above each site's real local horizon, live from **NASA/JPL Horizons**
* checks rover routes over the same LOLA terrain
* ranks every site-and-date option against the mission's rules, and explains why

When a launch slips or requirements change, it replans in seconds. Everything is built on NASA data, and every number is checked: Sun/Earth angles match JPL Horizons within 0.00003°.

## Project demo
*(Attach the 7-slide deck `presentation/LUNA_NAV_AI.pptx` or the 30-second video.)*

## Final project link
`<LINK>`

## Project details

**What it does**

* **Mission Command web app:**
  * set the mission type, landing dates and rules (maximum slope, minimum sunlight, maximum Earth blackout, maximum rover traverse)
  * watch seven planning agents work
  * explore the south pole in 3D on LOLA terrain
  * compare sites and dates, then replan
* **Default mission** (6 sites × 3 days × 96 h): the recommendation is the **rim of Shackleton crater** (89.78°S, 155.73°W). It gets sunlight for 96 of 96 h, keeps Earth in view for 96 of 96 h, has a 2.4° slope and a 7.5 km rover traverse. The runner-up is the Shackleton connecting ridge.

**How it works**

* **Member 1, terrain:** a FastAPI service that finds flat, high candidate sites in the LOLA 240 m south-polar elevation map.
* **Member 2, Sun & Earth visibility:** azimuth and elevation of the Sun and Earth hour by hour.
  * Source: live JPL Horizons, with an offline fallback to NASA NAIF SPICE (DE440).
  * Each site's horizon is computed from LOLA terrain. Visibility is geometric (no atmosphere), and libration comes from the ephemeris.
* **Member 3, navigation:** A* / Dijkstra rover routes with a slope limit, on the same LOLA terrain.
* **Member 4, multi-agent planner:** a 7-step LangGraph pipeline:
  1. supervisor
  2. site analysis
  3. visibility
  4. navigation
  5. scientific validation
  6. optimization (Pareto layers + MILP)
  7. evidence-only explanation
* **Member 5, frontend:** the Mission Command web app.

**Tools:** Python, FastAPI, LangGraph, SciPy, NumPy, SpiceyPy, Node.js, TypeScript, Express, React, OpenLayers.

**How we checked it** (full stack running on NASA data)

* 25/25 live API tests, with zero mock inputs.
* 206 unit tests passed.
* Sun/Earth angles agree with a direct JPL Horizons query within 0.00003°.
* Site elevations equal a direct read of the LOLA file.

**Goals**

* Give mission planners, educators and the public a quick way to compare landing sites and dates.
* Show why small changes in location or date change power and communication so much near the pole.

**Limits**

* Results are planning estimates, labelled UNVERIFIED (not independently reviewed). They are not flight decisions.
* 240 m pixels cannot show boulders.
* Routes check slope only.

## Use of AI and NASA data

**NASA data (core of every calculation)**

* **NASA LRO LOLA `LDEM_75S_240M`:** landing sites, slope, terrain horizon, rover routes and the 3D Moon.
* **NASA/JPL Horizons:** Sun and Earth positions from each site.
* **NASA NAIF SPICE kernels:** offline ephemeris and the Moon's body frame.
* We also consulted **ASU LROC QuickMap** and **NASA Moon Trek** (viewers of the same LRO data) to understand the terrain.

**AI**

* **Agents in the product:** the planning agents are LangGraph code, and every number comes from NASA data and deterministic science code.
  * Google Gemini is optional and does language only: it classifies the free-text request and writes a summary.
  * A checker rejects any Gemini text with a number that is not in the evidence.
  * Our submitted results ran with Gemini off.
* **In development:** the team used AI coding assistants, including Anthropic Claude (Claude Code), for coding, review, testing and documentation. All reported results were measured by running the code.

## References

* NASA PDS Geosciences Node: *LRO LOLA Gridded Data Records*, `LDEM_75S_240M`. https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/data/lola_gdr/
* NASA/JPL Solar System Dynamics: *Horizons System*. https://ssd.jpl.nasa.gov/horizons/
* NASA NAIF: *SPICE generic kernels*. https://naif.jpl.nasa.gov/pub/naif/generic_kernels/
* ASU LROC QuickMap: https://quickmap.lroc.asu.edu/
* NASA/JPL Moon Trek: https://trek.nasa.gov/moon/
* NASA Space Apps 2026, *Lunar Landing Site Navigator*: https://www.spaceappschallenge.org/2026/challenges/lunar-landing-site-navigator/
* Open-source software:
  * Python: FastAPI, Uvicorn, Pydantic, httpx, LangGraph, SciPy, NumPy, SpiceyPy, Matplotlib, pytest.
  * JavaScript/TypeScript: Node.js, Express, React, Vite, Vitest, OpenLayers, proj4, zod.
* AI services: Google Gemini API (optional); Anthropic Claude / Claude Code (development assistant).

## Team

* Shahad Tahir: terrain
* Roaa Alhejaili: Sun & Earth visibility
* Aseel Aldhahri: navigation
* Juri Almarwani (leader): multi-agent AI
* Abdualrhman Algharbani: frontend
