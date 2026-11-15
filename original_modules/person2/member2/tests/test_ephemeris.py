"""SPICE az/el validated against independent NASA/JPL Horizons values."""
from datetime import datetime

import numpy as np
import pytest

from visibility_planner import ephemeris as eph
from visibility_planner.kernels import load_kernels

pytestmark = pytest.mark.needs_kernels
TOL = 0.05


def _azel(lat, lon, utc, body):
    tr = eph.body_track(body, [eph.utc_to_et(utc)], lat, lon)
    return float(tr.az_deg[0]), float(tr.el_deg[0])


def _daz(a, b):
    return abs((a - b + 180) % 360 - 180)


def test_frame_is_moon_me():
    assert load_kernels() == "MOON_ME"


@pytest.mark.parametrize("lat,lon,body,az,el", [
    (-86.0, 129.8, "sun", 344.5666, 5.4128),
    (-86.0, 0.0, "earth", 357.3841, 0.4425),
    (-86.0, 0.0, "sun", 114.4776, -0.1001),
])
def test_golden_values_hand_checked(lat, lon, body, az, el):
    a, e = _azel(lat, lon, "2026-11-15T00:00:00Z", body)
    assert _daz(a, az) < TOL and abs(e - el) < TOL


def test_every_horizons_reference_row(horizons_reference):
    diffs = []
    for name, site in horizons_reference["sites"].items():
        az_tol = 0.5 if site["lat_deg"] < -89.5 else TOL
        for body in ("sun", "earth"):
            for row in site[body]:
                utc = datetime.strptime(row["time"], "%Y-%b-%d %H:%M").strftime("%Y-%m-%dT%H:%M:%SZ")
                a, e = _azel(site["lat_deg"], site["lon_deg_east"], utc, body)
                assert _daz(a, row["az_deg"]) < az_tol, (name, body, utc)
                assert abs(e - row["el_deg"]) < TOL, (name, body, utc)
                diffs.append((_daz(a, row["az_deg"]), abs(e - row["el_deg"])))
    assert len(diffs) == 174


def test_apparent_radii_computed_not_hardcoded():
    et = eph.utc_to_et("2026-11-15T00:00:00Z")
    sun = eph.body_track("sun", [et], -86, 0).angular_radius_deg[0]
    earth = eph.body_track("earth", [et], -86, 0).angular_radius_deg[0]
    assert 0.26 < sun < 0.28 and 0.9 < earth < 1.0


def test_time_round_trip():
    et = eph.utc_to_et("2026-11-15T12:34:56Z")
    assert eph.et_to_utc(et) == "2026-11-15T12:34:56Z"


def test_sun_elevation_rate_near_86s_is_tiny():
    ets = eph.utc_to_et("2026-11-16T00:00:00Z") + np.array([0.0, 3600.0])
    el = eph.body_track("sun", ets, -86, 0).el_deg
    assert 0.0 < abs(el[1] - el[0]) < 0.1   # ~0.03 deg/hour near the south pole


def test_vectorised_sun_earth_wrapper():
    out = eph.sun_earth_az_el(-86, 0, ["2026-11-15T00:00:00Z", "2026-11-15T06:00:00Z"])
    assert set(out) == {"sun", "earth"} and out["sun"].el_deg.shape == (2,)
    assert out["earth"].range_km[0] == pytest.approx(3.8e5, rel=0.08)
