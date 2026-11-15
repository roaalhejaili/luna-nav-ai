"""Terrain horizon ray-casting on analytic DEMs (exact answers, no data files needed)."""
import numpy as np
import pytest

from visibility_planner.terrain import (R_M, compute_horizon, destination,
                                        elevation_angle_deg)

SITE = (-86.0, 0.0)


class FlatSphere:
    def height_m(self, lat, lon):
        return np.zeros(np.broadcast(np.asarray(lat), np.asarray(lon)).shape)


class Ring:
    """Wall of height H between distances d0 and d1 from the site, flat elsewhere."""

    def __init__(self, h, d0, d1, az_range=None):
        self.h, self.d0, self.d1, self.az_range = h, d0, d1, az_range

    def height_m(self, lat, lon):
        lat, lon = np.broadcast_arrays(np.asarray(lat, float), np.asarray(lon, float))
        p1, l1 = np.radians(SITE[0]), np.radians(SITE[1])
        p2, l2 = np.radians(lat), np.radians(lon)
        d = R_M * np.arccos(np.clip(np.sin(p1) * np.sin(p2)
                                    + np.cos(p1) * np.cos(p2) * np.cos(l2 - l1), -1, 1))
        az = np.degrees(np.arctan2(np.sin(l2 - l1) * np.cos(p2), np.cos(p1) * np.sin(p2)
                                   - np.sin(p1) * np.cos(p2) * np.cos(l2 - l1))) % 360
        inside = (d >= self.d0) & (d <= self.d1)
        if self.az_range:
            a0, a1 = self.az_range
            inside &= ((az - a0) % 360) <= ((a1 - a0) % 360)
        return np.where(inside, self.h, 0.0)


def test_destination_north_and_east():
    lat, lon = destination(0.0, 10.0, 0.0, R_M * np.radians(1.0))
    assert (float(lat), float(lon)) == (pytest.approx(1.0), pytest.approx(10.0))
    lat, lon = destination(0.0, 10.0, 90.0, R_M * np.radians(1.0))
    assert (float(lat), float(lon)) == (pytest.approx(0.0, abs=1e-12), pytest.approx(11.0))


def test_elevation_angle_includes_curvature():
    # same height 100 km away: dips by theta/2 below horizontal
    el = elevation_angle_deg(0.0, 0.0, 100_000.0)
    assert float(el) == pytest.approx(-np.degrees(100_000.0 / R_M) / 2, rel=1e-6)


def test_flat_sphere_horizon_is_geometric_dip():
    prof, diag = compute_horizon(FlatSphere(), *SITE, observer_height_m=2.0, step_m=50,
                                 max_range_m=10_000, az_step_deg=10)
    dip = -np.degrees(np.sqrt(2 * 2.0 / R_M))          # about -0.087 deg
    assert np.allclose(prof.elevation_deg, dip, atol=0.003)
    assert diag["horizon_distance_m"][0] == pytest.approx(np.sqrt(2 * 2.0 * R_M), rel=0.05)


def test_ring_wall_matches_closed_form():
    prof, _ = compute_horizon(Ring(1000.0, 10_000, 10_500), *SITE, observer_height_m=2.0,
                              step_m=50, max_range_m=20_000, az_step_deg=15)
    expect = float(elevation_angle_deg(2.0, 1000.0, 10_000.0))
    # tolerance = one 50 m sampling step at 10 km (~0.03 deg): a ray may land just past the edge
    assert np.allclose(prof.elevation_deg, expect, atol=0.04)
    assert expect == pytest.approx(np.degrees(np.arctan(998 / 10_000)) - 0.165, abs=0.01)


def test_mountain_appears_at_correct_azimuth():
    prof, _ = compute_horizon(Ring(2000.0, 20_000, 22_000, az_range=(80, 100)), *SITE,
                              step_m=100, max_range_m=40_000, az_step_deg=5)
    el = dict(zip(prof.azimuth_deg, prof.elevation_deg))
    assert el[90.0] > 4.0                              # east: blocked by the mountain
    assert el[0.0] < 0 and el[180.0] < 0 and el[270.0] < 0
    assert prof.data_status == "REAL"


def test_no_data_at_site_rejected():
    class Empty:
        def height_m(self, lat, lon):
            return np.full(np.broadcast(np.asarray(lat), np.asarray(lon)).shape, np.nan)
    with pytest.raises(ValueError, match="no DEM data"):
        compute_horizon(Empty(), *SITE)
