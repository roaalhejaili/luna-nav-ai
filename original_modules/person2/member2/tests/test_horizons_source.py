"""NASA/JPL Horizons API data source: offline parsing tests + live tests (needs_network)."""
import json
from datetime import datetime, timezone

import numpy as np
import pytest

from visibility_planner import analyze_site
from visibility_planner.sources import (HorizonsSource, Site, UpstreamError, jd_to_utc,
                                        parse_horizons)

from .conftest import FIXTURES

T0 = datetime(2026, 11, 15, tzinfo=timezone.utc)


# ------------------------------------------------------------------ offline (captured responses)
@pytest.mark.parametrize("body,az0,el0,diam0", [("sun", 114.477644048, -0.100084477, 1941.612),
                                                ("earth", 357.384128688, 0.442492980, 6501.863)])
def test_parse_captured_horizons_response(body, az0, el0, diam0):
    d = json.loads((FIXTURES / f"horizons_api_sample_{body}.json").read_text())
    jd, az, el, diam = parse_horizons(d["result"])
    assert jd.size == 7 and jd_to_utc(jd[0]) == T0
    assert (az[0], el[0], diam[0]) == (az0, el0, diam0)
    assert np.all(np.diff(jd) > 0)


def test_parse_error_text_raises_reachable_upstream_error():
    with pytest.raises(UpstreamError) as e:
        parse_horizons("Cannot interpret date. Type '?!' for help.")
    assert e.value.reachable


def test_query_parameters_follow_conventions():
    p = HorizonsSource()._params("earth", Site(-86.0, -30.0, 1500.0), T0, T0, 6)
    assert p["COMMAND"] == "'399'" and p["CENTER"] == "'coord@301'"
    assert p["SITE_COORD"] == "'330.000000,-86.000000,1.500000'"   # east lon 0..360, alt km
    assert p["QUANTITIES"] == "'4,13'" and p["TIME_TYPE"] == "'UT'" and p["STEP_SIZE"] == "'6'"


def test_angular_radius_from_angular_diameter():
    d = json.loads((FIXTURES / "horizons_api_sample_earth.json").read_text())
    diam = parse_horizons(d["result"])[3][0]
    assert diam / 7200.0 == pytest.approx(0.903, abs=0.01)   # Earth radius as seen from Moon, deg


def test_offline_raises_unreachable(offline_horizons):
    with pytest.raises(UpstreamError) as e:
        HorizonsSource().track("sun", [T0, T0.replace(hour=1)], Site(-86, 0))
    assert not e.value.reachable


# --------------------------------------------------------------------------- live NASA API
@pytest.mark.needs_network
@pytest.mark.parametrize("lat,lon,body,az,el", [
    (-86.0, 129.8, "sun", 344.5666, 5.4128),
    (-86.0, 0.0, "earth", 357.3841, 0.4425),
    (-86.0, 0.0, "sun", 114.4776, -0.1001),
])
def test_live_golden_values(lat, lon, body, az, el):
    tr = HorizonsSource().track(body, [T0, T0.replace(hour=6)], Site(lat, lon))
    assert abs((tr.az_deg[0] - az + 180) % 360 - 180) < 0.05 and abs(tr.el_deg[0] - el) < 0.05


@pytest.mark.needs_network
def test_live_analyze_default_engine_uses_horizons_when_online():
    r = analyze_site({"site": {"site_id": "site_A", "lat_deg": -86.0, "lon_deg_east": 0.0},
                      "start_utc": "2026-11-15T00:00:00Z", "duration_days": 1, "step_minutes": 60})
    if r.data_source.fallback_reason:   # auto legitimately fell back (Horizons slow/unreachable)
        pytest.skip(f"Horizons did not answer within 15 s: {r.data_source.fallback_reason}")
    assert r.data_source.engine == "horizons" and not r.data_source.download_required
    assert r.data_source.url.startswith("https://ssd.jpl.nasa.gov/api/horizons.api")
    assert r.kernels == [] and r.data_status == "REAL" and r.source.startswith("NASA/JPL Horizons")
    assert r.windows[0].start_utc.endswith("Z") and len(r.time_series) == 25


@pytest.mark.needs_network
@pytest.mark.needs_kernels
def test_live_horizons_equals_spice(base_request):
    req = {**base_request, "horizon_profile_id": "ridge", "step_minutes": 20}
    hz = analyze_site({**req, "engine": "horizons"})
    sp = analyze_site({**req, "engine": "spice"})
    for a, b in zip(hz.time_series, sp.time_series):
        assert abs(a.sun_el_deg - b.sun_el_deg) <= 2e-4 and abs(a.earth_el_deg - b.earth_el_deg) <= 2e-4
    assert len(hz.windows) == len(sp.windows)
    for a, b in zip(hz.windows, sp.windows):
        da = abs((datetime.fromisoformat(a.start_utc[:-1]) - datetime.fromisoformat(b.start_utc[:-1])).total_seconds())
        db = abs((datetime.fromisoformat(a.end_utc[:-1]) - datetime.fromisoformat(b.end_utc[:-1])).total_seconds())
        assert (a.body, a.kind) == (b.body, b.kind) and da <= 2 and db <= 2
    assert hz.summary.sun_visible_fraction == pytest.approx(sp.summary.sun_visible_fraction, abs=1e-4)


@pytest.mark.needs_network
def test_live_off_grid_end_and_compare():
    r = analyze_site({"site": {"lat_deg": -86, "lon_deg_east": 0}, "start_utc":
                      "2026-11-15T00:00:00Z", "end_utc": "2026-11-15T05:07:00Z",
                      "step_minutes": 60})
    assert [p.utc for p in r.time_series][-2:] == ["2026-11-15T05:00:00Z", "2026-11-15T05:07:00Z"]
