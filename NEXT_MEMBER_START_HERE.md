# Integration handoff

1. In Windows PowerShell from this project directory, run `uv venv --python 3.11 .venv` (or use an installed Python 3.11+), then `uv pip install --python .venv\Scripts\python.exe -r requirements.txt`.
2. Run `.venv\Scripts\python.exe -m pytest tests -q`, `.venv\Scripts\python.exe -m examples.verify_demo`, and `.venv\Scripts\python.exe -m uvicorn api.main:app`.
3. If PyPI DNS fails, check `Resolve-DnsName pypi.org` and retry on a network with PyPI access. For an offline machine, download compatible wheels on a connected Windows machine with `py -m pip download -r requirements.txt -d wheelhouse`, copy the `wheelhouse` directory into this project, then run `uv pip install --python .venv\Scripts\python.exe --no-index --find-links wheelhouse -r requirements.txt`. Match the Python version and architecture on both machines. Do not include `.venv` or `wheelhouse` in the source ZIP.
4. Send `examples/demo_request.json` to `POST /mission/plan`; inspect `/openapi.json`.
5. Implement the three GET service contracts in `API_CONTRACT.md` and return exact Pydantic field names and provenance. Agree on lunar elevation datum, coordinate frame, site IDs and duration convention before using real measurements.
6. Set the appropriate `LUNA_*_URL` environment variable for each ready module. Leave other URLs unset to keep their mocks.
7. Send the returned plan plus changed requirements to `/mission/replan`. Send requirements to `/mission/compare` for baseline metrics.
8. Keep `allow_mock_recommendation=false` for any decision requiring verified data. Check warnings and every field's provenance.

Verification on 2026-11-14: 5 tests passed with Python 3.14.4; the four-endpoint mock demo passed. See `PROJECT_STATUS.md` for the observed result and remaining blockers.

## Current team integration

The earlier verification line above is historical. Current results: Person 4 has 22 passing tests, Person 1 has 10, Person 2 has 90 passing with 44 skipped, and Person 3 has 30 passing Vitest tests plus a passing TypeScript typecheck. Actual REST adapters are implemented in `tools/member_adapters.py`; the pristine Person 3 ZIP is preserved at `original_modules/person3_original.zip`. Run `powershell -ExecutionPolicy Bypass -File scripts/start_integrated.ps1` after installing Python and Node requirements. For Person 5, use `FRONTEND_INTEGRATION_GUIDE.md`, `API_REFERENCE.md`, `openapi.json`, and `FRONTEND_DATA_EXAMPLES/`.
