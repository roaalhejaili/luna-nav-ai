"""Horizon profiles: interpolation, validation, fixtures, terrain <= geometric."""
import json

import numpy as np
import pytest
from pydantic import ValidationError

from visibility_planner.horizon import (SYNTHETIC_PROFILES, HorizonProfile, crater_rim_horizon,
                                        flat_horizon, ridge_horizon, synthetic_profile)
from visibility_planner.windows import find_windows, total_duration

from .conftest import FIXTURES


def _profile(az, el, status="MOCK"):
    return HorizonProfile(site_id="t", data_status=status, source="unit", azimuth_deg=az,
                          elevation_deg=el)


def test_wraparound_interpolation_359_9_to_0_1():
    p = _profile([0.0, 90.0, 180.0, 270.0, 359.0], [4.0, 0.0, 0.0, 0.0, 2.0])
    # between 359 (2 deg) and 360==0 (4 deg)
    assert p.elevation_at(359.9) == pytest.approx(3.8)
    assert p.elevation_at(0.1) == pytest.approx(4.0 - 0.1 * 4 / 90)
    assert p.elevation_at(-0.5) == pytest.approx(p.elevation_at(359.5))
    assert p.elevation_at(720.0) == pytest.approx(4.0)


def test_unsorted_input_is_handled():
    p = _profile([270.0, 0.0, 90.0], [1.0, 3.0, 2.0])
    assert p.elevation_at(45) == pytest.approx(2.5)


def test_synthetic_shapes():
    assert np.all(np.asarray(flat_horizon().elevation_deg) == 0)
    r = ridge_horizon()
    assert r.elevation_at(0) == pytest.approx(3.0) and r.elevation_at(180) == 0
    c = crater_rim_horizon()
    el = np.asarray(c.elevation_deg)
    assert c.elevation_at(160) == pytest.approx(0, abs=1e-6)
    wall = el[(np.abs(((np.arange(360) - 160 + 180) % 360) - 180)) > 20]
    assert wall.min() >= 1.0 - 1e-6 and wall.max() <= 4.0 + 1e-6
    for p in (flat_horizon(), r, c):
        assert p.data_status == "MOCK" and p.source == "synthetic_fixture"


@pytest.mark.parametrize("pid", list(SYNTHETIC_PROFILES))
def test_fixture_files_match_generator(pid):
    disk = json.loads((FIXTURES / f"horizon_{pid}.json").read_text())
    assert disk == synthetic_profile(pid, "fixture").model_dump(mode="json")
    assert HorizonProfile.from_file(FIXTURES / f"horizon_{pid}.json").data_status == "MOCK"


@pytest.mark.parametrize("az,el,status", [
    ([0, 360], [0, 0], "MOCK"),           # 360 not allowed
    ([0, 10], [0, 95], "MOCK"),           # elevation out of range
    ([0, 10, 20], [0, 1], "MOCK"),        # length mismatch
    ([5, 5], [0, 1], "MOCK"),             # duplicate azimuth
    ([0, 10], [0, 1], "PARTIAL"),         # profile must be REAL or MOCK
])
def test_invalid_profiles_rejected(az, el, status):
    with pytest.raises(ValidationError):
        _profile(az, el, status)


def test_unknown_profile_id():
    with pytest.raises(KeyError):
        synthetic_profile("nope")


def test_ridge_blocks_body_above_zero_but_below_ridge():
    """Body at az 0 with elevation 0.5..2 deg: geometric visible, terrain blocked by 3 deg ridge."""
    ridge = ridge_horizon()
    t = np.linspace(0, 100, 101)
    el = 0.5 + 1.5 * t / 100
    az = np.zeros_like(t)
    geo = find_windows(t, el)
    ter = find_windows(t, el - ridge.elevation_at(az))
    assert total_duration(geo) == pytest.approx(100) and ter == []


def test_terrain_never_exceeds_geometric_for_nonnegative_horizon():
    rng = np.random.default_rng(0)
    t = np.linspace(0, 1000, 2001)
    for prof in (ridge_horizon(), crater_rim_horizon()):
        el = 5 * np.sin(t / 50) + rng.normal(0, 0.2, t.size)
        az = (t * 0.37) % 360
        geo = total_duration(find_windows(t, el))
        ter = total_duration(find_windows(t, el - prof.elevation_at(az)))
        assert ter <= geo + 1e-9
