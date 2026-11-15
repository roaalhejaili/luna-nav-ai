"""Regenerate derived files from code. Run after changing models or horizon shapes:

    python scripts/generate_fixtures.py

Writes:
  tests/fixtures/horizon_{flat,ridge,crater_rim}.json      synthetic horizons (MOCK)
  schemas/*.schema.json                                     JSON Schemas of the API contract
  visibility_planner/mock_data/mock_*_response.json         labelled MOCK example responses
  examples/mock_visibility_response.json, examples/mock_compare_response.json (copies)

The MOCK responses are shape examples. Their numbers come from a real SPICE run (nothing
invented), but they are RELABELLED data_status "MOCK" so nobody treats them as science output.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from visibility_planner import models  # noqa: E402
from visibility_planner.horizon import SYNTHETIC_PROFILES  # noqa: E402
from visibility_planner.planner import analyze_site, compare_windows  # noqa: E402

MOCK_NOTE = ("MOCK example for integration only. Numbers copied from a real NASA-data run of the "
             "request in 'mission'; regenerate with scripts/generate_fixtures.py. Do not use "
             "for science.")


def dump(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1) + "\n", encoding="utf-8", newline="\n")
    print("wrote", path.relative_to(ROOT))


def relabel(payload: dict) -> dict:
    payload["data_status"] = "MOCK"
    payload["source"] = "synthetic_fixture (" + MOCK_NOTE + ")"
    payload.pop("generated_utc", None)
    if payload.get("data_source"):
        payload["data_source"] = {
            "engine": "mock", "name": "synthetic_fixture (numbers copied from a run of engine "
            f"'{payload['data_source']['engine']}': {payload['data_source']['name']})",
            "url": payload["data_source"].get("url"), "requests": 0,
            "download_required": False}
    for w in payload.get("windows", []):
        if "data_status" in w:
            w["data_status"] = "MOCK"
    return payload


def main() -> None:
    for pid, fn in SYNTHETIC_PROFILES.items():
        dump(ROOT / "tests" / "fixtures" / f"horizon_{pid}.json",
             fn("fixture").model_dump(mode="json"))

    for name, model in [("visibility_request", models.VisibilityRequest),
                        ("visibility_result", models.VisibilityResult),
                        ("compare_request", models.CompareRequest),
                        ("comparison_result", models.ComparisonResult),
                        ("horizon_profile", models.HorizonProfile),
                        ("error_response", models.ErrorResponse)]:
        dump(ROOT / "schemas" / f"{name}.schema.json", model.model_json_schema())

    site = {"site_id": "site_A", "lat_deg": -86.0, "lon_deg_east": 0.0, "alt_m": 0.0}
    mission = {"mission_id": "MOCK-EXAMPLE", "mission_type": "science",
               "target": "lunar south pole", "note": MOCK_NOTE}
    res = analyze_site({"site": site, "start_utc": "2026-11-15T00:00:00Z", "duration_days": 2,
                        "step_minutes": 60, "horizon_profile_id": "ridge", "mission": mission})
    a = relabel(res.model_dump(mode="json"))
    cmp_ = compare_windows({"site": site, "horizon_profile_id": "ridge", "step_minutes": 30,
                            "mission": mission, "windows": [
                                {"label": "A", "start_utc": "2026-11-15T00:00:00Z", "duration_days": 7},
                                {"label": "B", "start_utc": "2026-11-29T00:00:00Z", "duration_days": 7}]})
    c = relabel(cmp_.model_dump(mode="json"))
    for d in (ROOT / "visibility_planner" / "mock_data", ROOT / "examples"):
        dump(d / "mock_visibility_response.json", a)
        dump(d / "mock_compare_response.json", c)


if __name__ == "__main__":
    main()
