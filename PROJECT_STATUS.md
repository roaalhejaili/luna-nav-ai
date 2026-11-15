# Project status — 2026-11-14

**PARTIALLY READY for integration.** The standalone MOCK API works and the LangGraph graph executes seven nodes, including conditional navigation. Real teammate APIs and scientific data remain unverified. No flight recommendation is supported.

Verification: `.venv\Scripts\python.exe -m pytest tests -q` → **20 passed, 0 failed, 0 skipped**, 13 LangSmith deprecation warnings. `.venv\Scripts\python.exe -m examples.verify_demo` passed: all four endpoints returned 200; 6 mock site/date candidates, 4 feasible; recommended MOCK site A on 2030-01-02T00:00:00Z. The demo is synthetic.

Graph: `START → supervisor → site_analysis → visibility_analysis → [navigation_analysis when required] → validation → optimization → explanation → END`. Specialist service calls, constraint checks, optimization and explanation occur inside graph nodes. A recursion limit of 12 bounds execution. The optional LLM uses structured output for mission type and explanation focus with one 5-second attempt; without a key, the graph uses deterministic interpretation and explanation. No LLM-generated measurements are accepted. The live LLM path was not tested.

Optimization: hard constraints filter candidates. Weighted utility supports mission-specific priorities. SciPy MILP makes binary site/date selections within Pareto layers. The baseline ranks feasible options by weighted score. These are alternative ranking methods; no measured superiority claim is made.

Safety: MOCK and UNVERIFIED status are checked across all available measurements. MOCK warnings and explanations remain explicit; `allow_mock_recommendation=false` prevents mock recommendations. Missing schema fields fail validation. Timestamps must have timezone information and are normalized to UTC. A self-declared VERIFIED source is not independently authenticated, elevation datum is not modeled, and scientific sources/uncertainties are not externally validated.

Remaining blockers: actual Persons 1–3 service compatibility, real ephemeris/terrain data and datum alignment, live LLM path, live network failure behavior, and Person 5 dashboard integration. See `TEST_REPORT.md` for evidence and coverage limits.

## Integration update — 2026-11-14

Person 1–3 source is preserved under `original_modules/`; the pristine Person 3 archive is `original_modules/person3_original.zip`. Person 1 original suite: 10 passed. Person 2 original suite: 90 passed, 44 skipped. Person 3: 30 Vitest tests, `pnpm typecheck`, and Moon Explorer build pass after adding the missing direct Express core types dev dependency to its integration copy. Person 4 suite: 22 passed. Cross-module tests exercise Person 1's actual app and Person 2's published MOCK fixture through Person 4's graph. The Person 3 actual Express server returned health 200, and the Person 4 adapter received a MOCK route of 74,555.4 m with `NOT_VALIDATED` provenance. This was synthetic terrain, not an operational route. The backend remains **PARTIALLY READY** for science because real NASA-backed mission recommendations, combined live Persons 1–3 planning, datum alignment, and Person 5 dashboard integration are unverified.
