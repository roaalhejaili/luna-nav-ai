"""analyze_site / compare_windows: contract, data_status rules, physics sanity, determinism."""
import json
import re

import pytest

from visibility_planner import analyze_site, compare_windows
from visibility_planner import ephemeris as eph
from visibility_planner.models import ComparisonResult, VisibilityResult

pytestmark = pytest.mark.needs_kernels
ISO_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def test_output_validates_and_is_json(base_request):
    r = analyze_site(base_request)
    payload = json.loads(json.dumps(r.model_dump(mode="json")))
    VisibilityResult.model_validate(payload)
    assert payload["body_frame"] == "MOON_ME" and payload["moon_radius_km"] == 1737.4
    assert len(payload["time_series"]) == 2 * 48 + 1


def test_all_timestamps_iso_utc_z(base_request):
    p = analyze_site({**base_request, "horizon_profile_id": "ridge"}).model_dump(mode="json")
    stamps = [p["start_utc"], p["end_utc"], p["generated_utc"]]
    stamps += [x["utc"] for x in p["time_series"]]
    stamps += [w[k] for w in p["windows"] for k in ("start_utc", "end_utc")]
    assert all(ISO_Z.match(s) for s in stamps)


def test_data_status_rules(base_request):
    geo = analyze_site(base_request)
    assert geo.data_status == "REAL" and geo.horizon.type == "geometric"
    assert geo.summary.sun_visible_fraction_terrain is None
    mock = analyze_site({**base_request, "horizon_profile_id": "ridge"})
    assert mock.data_status == "PARTIAL" and mock.horizon.data_status == "MOCK"
    real_prof = {"site_id": "site_A", "data_status": "REAL", "source": "member01_lola_test",
                 "azimuth_deg": [0, 180], "elevation_deg": [1.0, 1.0]}
    real = analyze_site({**base_request, "horizon_profile": real_prof})
    assert real.data_status == "REAL" and real.horizon.type == "terrain"


def test_deterministic_for_same_input(base_request):
    a = analyze_site(base_request).model_dump(mode="json")
    b = analyze_site(base_request).model_dump(mode="json")
    a.pop("generated_utc"), b.pop("generated_utc")
    assert a == b


def test_terrain_fraction_le_geometric_and_flat_equals_geometric(base_request):
    for pid in ("ridge", "crater_rim"):
        s = analyze_site({**base_request, "horizon_profile_id": pid}).summary
        assert s.sun_visible_fraction_terrain <= s.sun_visible_fraction
        assert s.earth_visible_fraction_terrain <= s.earth_visible_fraction
    s = analyze_site({**base_request, "horizon_profile_id": "flat"}).summary
    assert s.sun_visible_fraction_terrain == s.sun_visible_fraction


def test_upper_limb_at_least_center(base_request):
    c = analyze_site(base_request).summary
    u = analyze_site({**base_request, "visibility_definition": "upper_limb"}).summary
    assert u.sun_visible_fraction >= c.sun_visible_fraction
    assert u.earth_visible_fraction >= c.earth_visible_fraction


def test_refined_window_edge_is_a_true_crossing(base_request):
    r = analyze_site(base_request)
    rise = [w for w in r.windows if w.body == "sun" and w.kind == "geometric"
            and not w.starts_at_interval_start][0]
    et = eph.utc_to_et(rise.start_utc)
    el = eph.body_track("sun", [et - 60, et + 60], -86, 0).el_deg
    assert el[0] < 0 < el[1]                    # sunrise bracketed within +-1 minute
    assert rise.start_utc == "2026-11-15T03:05:24Z"


def test_fractions_and_windows_consistent(base_request):
    r = analyze_site(base_request)
    span_h = 48.0
    for body, gap, frac in (("sun", "dark", r.summary.sun_visible_fraction),
                            ("earth", "no_contact", r.summary.earth_visible_fraction)):
        vis = sum(w.duration_hours for w in r.windows if w.body == body and w.kind == "geometric")
        off = sum(w.duration_hours for w in r.windows if w.body == gap and w.kind == "geometric")
        assert vis + off == pytest.approx(span_h, abs=1e-3)
        assert vis / span_h == pytest.approx(frac, abs=1e-4)


def test_far_side_never_sees_earth_near_side_always():
    far = analyze_site({"engine": "spice", "site": {"lat_deg": 0, "lon_deg_east": 180}, "start_utc":
                        "2026-11-15T00:00:00Z", "duration_days": 30, "step_minutes": 120,
                        "include_time_series": False})
    assert far.summary.earth_visible_fraction == 0 and far.summary.longest_no_contact_hours == 720
    near = analyze_site({"engine": "spice", "site": {"lat_deg": 0, "lon_deg_east": 0}, "start_utc":
                         "2026-11-15T00:00:00Z", "duration_days": 30, "step_minutes": 120,
                         "include_time_series": False})
    assert near.summary.earth_visible_fraction == 1


def test_lunar_day_length_at_86s():
    r = analyze_site({"engine": "spice", "site": {"lat_deg": -86, "lon_deg_east": 0}, "start_utc":
                      "2026-11-15T00:00:00Z", "duration_days": 60, "step_minutes": 30,
                      "include_time_series": False})
    rises = [w.start_utc for w in r.windows if w.body == "sun" and w.kind == "geometric"]
    gap_days = (eph.utc_to_et(rises[1]) - eph.utc_to_et(rises[0])) / 86400
    assert 29.0 < gap_days < 30.5                 # synodic month ~29.5 days


def test_no_time_series_option(base_request):
    r = analyze_site({**base_request, "include_time_series": False})
    assert r.time_series == [] and r.windows


def test_mission_context_echoed(base_request):
    m = {"mission_id": "M1", "mission_type": "science", "target": "south pole",
         "constraints": {"max_dark_hours": 50}}
    assert analyze_site({**base_request, "mission": m}).mission.model_dump(exclude_none=True) == m


def test_compare_windows_side_by_side(base_request):
    req = {"site": base_request["site"], "step_minutes": 60, "horizon_profile_id": "ridge",
           "engine": "spice",
           "windows": [{"label": "A", "start_utc": "2026-11-15T00:00:00Z", "duration_days": 3},
                       {"label": "B", "start_utc": "2026-12-05T00:00:00Z",
                        "end_utc": "2026-12-08T00:00:00Z"}]}
    c = compare_windows(req)
    ComparisonResult.model_validate(c.model_dump(mode="json"))
    assert [w.label for w in c.windows] == ["A", "B"]
    assert c.table["longest_dark_hours"] == [w.summary.longest_dark_hours for w in c.windows]
    assert c.windows[1].summary.longest_dark_hours > c.windows[0].summary.longest_dark_hours
    assert "rank" not in json.dumps(c.model_dump(mode="json")).lower()
    single = analyze_site({"engine": "spice", "site": base_request["site"],
                           "start_utc": "2026-11-15T00:00:00Z",
                           "duration_days": 3, "step_minutes": 60, "horizon_profile_id": "ridge"})
    assert c.windows[0].summary == single.summary


def test_time_until_sunset_and_solar_elevation_metrics(base_request):
    """Sun up at start (2026-12-01, 86S 0E) and sets 2026-12-03T13:58:41Z (see 59-day run)."""
    r = analyze_site({**base_request, "start_utc": "2026-12-01T00:00:00Z", "duration_days": 4,
                      "include_time_series": False})
    s = r.summary
    assert s.hours_until_sunset == pytest.approx(61.978, abs=0.01)
    assert s.hours_until_earthset is None or s.hours_until_earthset > 0
    assert s.sun_elevation_max_deg >= s.sun_elevation_mean_deg
    assert analyze_site(base_request).summary.hours_until_sunset is None   # Sun down at start


def test_spice_result_reports_its_data_source(base_request):
    r = analyze_site(base_request)
    assert r.data_source.engine == "spice" and r.data_source.download_required
    assert len(r.kernels) == 5 and r.source.startswith("NASA NAIF SPICE")
