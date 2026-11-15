"""CLI behaviour and contract artefacts (schemas, mock files) staying in sync with the code."""
import json

import pytest

from visibility_planner import models
from visibility_planner.cli import EXIT_BAD_INPUT, EXIT_NO_KERNELS, EXIT_OK, EXIT_UPSTREAM, main
from visibility_planner.planner import MOCK_DIR

from .conftest import ROOT


@pytest.mark.needs_kernels
def test_cli_writes_valid_json(tmp_path, capsys):
    out = tmp_path / "r.json"
    rc = main(["--lat", "-86", "--lon", "0", "--start", "2026-11-15T00:00:00Z", "--days", "1",
               "--step-min", "60", "--horizon-id", "ridge", "--engine", "spice", "--out", str(out)])
    assert rc == EXIT_OK
    models.VisibilityResult.model_validate_json(out.read_text())
    assert json.loads(capsys.readouterr().out)["data_status"] == "PARTIAL"


@pytest.mark.needs_kernels
def test_cli_request_file_and_horizon_file(tmp_path):
    out = tmp_path / "r.json"
    rc = main(["--request", str(ROOT / "examples" / "scenario_1.json"), "--days", "1",
               "--horizon", str(ROOT / "tests" / "fixtures" / "horizon_crater_rim.json"),
               "--no-time-series", "--engine", "spice", "--out", str(out)])
    assert rc == EXIT_OK
    r = json.loads(out.read_text())
    assert r["horizon"]["profile_id"] == "crater_rim" and r["time_series"] == []
    assert r["site_id"] == "site_A_near_side_86S"


def test_cli_bad_input_exit_code(capsys):
    assert main(["--lat", "95", "--lon", "0", "--start", "2026-11-15T00:00:00Z", "--days", "1"]) \
        == EXIT_BAD_INPUT
    assert "lat_deg" in capsys.readouterr().err
    assert main(["--lat", "0", "--lon", "0", "--start", "2026-11-15T00:00:00", "--days", "1"]) \
        == EXIT_BAD_INPUT


def test_cli_missing_kernels_exit_code(tmp_path, capsys):
    rc = main(["--lat", "0", "--lon", "0", "--start", "2026-11-15T00:00:00Z", "--days", "1",
               "--engine", "spice", "--kernel-dir", str(tmp_path)])
    assert rc == EXIT_NO_KERNELS and "fetch_kernels" in capsys.readouterr().err


@pytest.mark.parametrize("name,model", [
    ("visibility_request", models.VisibilityRequest), ("visibility_result", models.VisibilityResult),
    ("compare_request", models.CompareRequest), ("comparison_result", models.ComparisonResult),
    ("horizon_profile", models.HorizonProfile), ("error_response", models.ErrorResponse)])
def test_published_json_schemas_up_to_date(name, model):
    disk = json.loads((ROOT / "schemas" / f"{name}.schema.json").read_text())
    assert disk == model.model_json_schema(), "run python scripts/generate_fixtures.py"


@pytest.mark.parametrize("name,model", [("mock_visibility_response.json", models.VisibilityResult),
                                        ("mock_compare_response.json", models.ComparisonResult)])
def test_mock_files_valid_labelled_and_identical(name, model):
    pkg = json.loads((MOCK_DIR / name).read_text())
    ex = json.loads((ROOT / "examples" / name).read_text())
    assert pkg == ex
    model.model_validate(pkg)
    assert pkg["data_status"] == "MOCK" and pkg["source"].startswith("synthetic_fixture")


@pytest.mark.parametrize("n", [1, 2, 3])
def test_scenarios_are_valid_requests(n):
    models.VisibilityRequest.model_validate_json(
        (ROOT / "examples" / f"scenario_{n}.json").read_text())


def test_cli_horizons_unreachable_exit_code(offline_horizons, capsys):
    rc = main(["--lat", "0", "--lon", "0", "--start", "2026-11-15T00:00:00Z", "--days", "1",
               "--engine", "horizons"])
    assert rc == EXIT_UPSTREAM and "Horizons" in capsys.readouterr().err


@pytest.mark.needs_kernels
def test_cli_default_auto_falls_back_offline(offline_horizons, tmp_path, capsys):
    out = tmp_path / "r.json"
    rc = main(["--lat", "-86", "--lon", "0", "--start", "2026-11-15T00:00:00Z", "--days", "1",
               "--step-min", "60", "--out", str(out)])
    assert rc == EXIT_OK and json.loads(capsys.readouterr().out)["engine"] == "spice"
    assert "unreachable" in json.loads(out.read_text())["data_source"]["fallback_reason"]
