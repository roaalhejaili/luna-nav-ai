"""Topocentric geometry without SPICE."""
import numpy as np
import pytest

from visibility_planner.frames import MOON_RADIUS_KM, site_vector_km, to_az_el, topocentric_basis

SITES = [(0, 0), (-86, 0), (-86, 129.8), (45, -120), (-89.9, 129.8), (89, 300)]


@pytest.mark.parametrize("lat,lon", SITES)
def test_basis_orthonormal_right_handed(lat, lon):
    up, east, north = topocentric_basis(lat, lon)
    m = np.vstack([east, north, up])
    np.testing.assert_allclose(m @ m.T, np.eye(3), atol=1e-12)
    np.testing.assert_allclose(np.cross(east, north), up, atol=1e-12)


def test_equator_north_is_plus_z():
    _, east, north = topocentric_basis(0, 0)
    np.testing.assert_allclose(north, [0, 0, 1], atol=1e-12)
    np.testing.assert_allclose(east, [0, 1, 0], atol=1e-12)


@pytest.mark.parametrize("lat,lon", SITES)
def test_cardinal_directions(lat, lon):
    up, east, north = topocentric_basis(lat, lon)
    assert to_az_el(up, lat, lon)[1] == pytest.approx(90.0)
    az, el = to_az_el(east, lat, lon)
    assert (az, el) == (pytest.approx(90.0), pytest.approx(0.0, abs=1e-9))
    az, el = to_az_el(north, lat, lon)
    assert min(az, 360 - az) == pytest.approx(0.0, abs=1e-9) and el == pytest.approx(0, abs=1e-9)
    az, _ = to_az_el(-north, lat, lon)
    assert az == pytest.approx(180.0)
    az, _ = to_az_el(-east, lat, lon)
    assert az == pytest.approx(270.0)


def test_elevation_of_tilted_vector_and_vectorised():
    up, east, north = topocentric_basis(-30, 40)
    v = np.vstack([np.cos(np.radians(10)) * north + np.sin(np.radians(10)) * up, -up])
    az, el = to_az_el(v, -30, 40)
    np.testing.assert_allclose(el, [10.0, -90.0], atol=1e-9)
    assert az.shape == (2,)


def test_site_vector_radius_and_altitude_in_meters():
    assert np.linalg.norm(site_vector_km(-86, 0)) == pytest.approx(MOON_RADIUS_KM)
    assert np.linalg.norm(site_vector_km(-86, 0, alt_m=1000)) == pytest.approx(MOON_RADIUS_KM + 1)
