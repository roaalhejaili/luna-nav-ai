# Integration report

| Module | Actual input | Connection status |
|---|---|---|
| Person 1 Landing Site Analyzer | Supplied ZIP; unchanged source in `original_modules/person1` | POST adapter implemented; its 10 original tests pass; adapter exercised against actual FastAPI app in MOCK mode. |
| Person 2 Visibility Planner | Supplied v1.2 ZIP; unchanged source in `original_modules/person2/member2` | POST adapter implemented; contract fixture mapping tested. Full original suite and live NASA execution are reported separately in `TEST_REPORT.md`. |
| Person 3 Moon Navigation | Pristine supplied ZIP preserved as `original_modules/person3_original.zip`; integration copy under `original_modules/person3/moon_navigation` | Added direct `@types/express-serve-static-core` dev dependency. `pnpm typecheck`, 30 Vitest tests, and Moon Explorer build pass. Actual Express health returned 200; Person 4's route adapter returned a 74,555.4 m MOCK route with `NOT_VALIDATED` provenance. |
| Person 4 Mission Optimizer | Current workspace | Public API and LangGraph retained; adapters selected by environment URLs. |
| Person 5 Dashboard | Not supplied | API, OpenAPI and frontend handoff prepared; no UI code changed. |

Critical schema differences are resolved in adapters: Person 1 uses POST region analysis and nested terrain fields with `MEAN_EARTH_POLAR_AXIS`; Person 2 uses POST site/window analysis, `MOON_ME`, fractions and terrain-aware summary metrics; Person 3 uses POST start/target route planning in `IAU_MOON_ME`. Suppliers use `REAL/MOCK/PARTIAL/UNAVAILABLE`, while Person 4 exposes `VERIFIED/MOCK/UNVERIFIED`. Real/partial supplier claims remain UNVERIFIED until independent review. Person 3's live adapter test used synthetic terrain and does not establish route operational validity.
