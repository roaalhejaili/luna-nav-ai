"""Input validation and missing-kernel handling (no SPICE math needed)."""
import pytest
from pydantic import ValidationError

from visibility_planner import KernelError, VisibilityRequest, analyze_site
from visibility_planner.kernels import load_kernels, missing_kernels

OK = {"site": {"lat_deg": -86, "lon_deg_east": 0}, "start_utc": "2026-11-15T00:00:00Z",
      "duration_days": 1, "engine": "spice"}


def _bad(**changes):
    req = {**OK, **changes}
    with pytest.raises(ValidationError) as e:
        VisibilityRequest.model_validate(req)
    return str(e.value)


def test_naive_datetime_rejected():
    assert "timezone-aware" in _bad(start_utc="2026-11-15T00:00:00")


def test_latitude_out_of_range():
    _bad(site={"lat_deg": 91, "lon_deg_east": 0})
    _bad(site={"lat_deg": -90.5, "lon_deg_east": 0})


def test_end_before_start_and_both_end_and_duration():
    _bad(duration_days=None, end_utc="2026-11-14T00:00:00Z")
    assert "exactly one" in _bad(end_utc="2026-11-16T00:00:00Z")
    assert "exactly one" in _bad(duration_days=None)


def test_too_many_samples_and_bad_step():
    assert "too many samples" in _bad(duration_days=400, step_minutes=1)
    _bad(step_minutes=0)


def test_unknown_fields_and_bad_enum_rejected():
    _bad(foo=1)
    _bad(visibility_definition="edge")
    _bad(engine="google")


def test_default_engine_is_auto():
    req = {k: v for k, v in OK.items() if k != "engine"}
    assert VisibilityRequest.model_validate(req).engine == "auto"


def test_both_horizon_inputs_rejected():
    prof = {"site_id": "x", "data_status": "MOCK", "source": "s", "azimuth_deg": [0, 1],
            "elevation_deg": [0, 0]}
    _bad(horizon_profile=prof, horizon_profile_id="ridge")


def test_offset_timezone_normalised_to_utc_and_lon_normalised():
    r = VisibilityRequest.model_validate({**OK, "start_utc": "2026-11-15T03:00:00+03:00",
                                          "site": {"lat_deg": 0, "lon_deg_east": 270}})
    assert r.start_utc.isoformat() == "2026-11-15T00:00:00+00:00"
    assert r.site.lon_deg_east == -90


def test_missing_kernel_directory(tmp_path):
    with pytest.raises(KernelError, match="not found"):
        load_kernels(tmp_path / "nope")
    (tmp_path / "naif0012.tls").write_text("x")
    assert "naif0012.tls" not in missing_kernels(tmp_path)
    with pytest.raises(KernelError, match="Missing SPICE kernels"):
        analyze_site(OK, kernel_dir=tmp_path)


def test_mock_mode_works_without_kernels(tmp_path):
    r = analyze_site({**OK, "use_mock": True}, kernel_dir=tmp_path / "nope")
    assert r.data_status == "MOCK"
