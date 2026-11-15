"""NASA LOLA LDEM_75S_240M: projection, orientation and REAL horizons (needs_lola)."""
import numpy as np
import pytest

from visibility_planner import analyze_site
from visibility_planner.lola import LolaDEM, TerrainError, parse_label
from visibility_planner.terrain import lola_horizon

from .conftest import FIXTURES

pytestmark = pytest.mark.needs_lola


@pytest.fixture(scope="module")
def dem():
    return LolaDEM.open(auto_download=False)


def test_label_and_size(dem):
    assert dem.n == 3812 and dem.scale_m == 240 and dem.max_lat_deg == -75
    assert dem.label["SCALING_FACTOR"] == 0.5


def test_projection_round_trip(dem):
    lat = np.array([-89.99, -88.0, -85.0, -80.0, -76.0])
    lon = np.array([0.0, 45.0, -120.0, 179.0, -90.0])
    i, j = dem.latlon_to_pixel(lat, lon)
    la, lo = dem.pixel_to_latlon(i, j)
    np.testing.assert_allclose(la, lat, atol=1e-9)
    np.testing.assert_allclose((lo - lon + 180) % 360 - 180, 0, atol=1e-7)


def test_catalog_text_orientation(dem):
    """DSMAP_POLAR.CAT: in the south, lon 0 is straight up, lon 90E to the right."""
    c = dem.n / 2 + 0.5
    i, j = dem.latlon_to_pixel(-85.0, 0.0)
    assert i == pytest.approx(c) and j < c          # up = smaller line number
    i, j = dem.latlon_to_pixel(-85.0, 90.0)
    assert i > c and j == pytest.approx(c)          # right = larger sample number


@pytest.mark.parametrize("name,lat,lon", [("Shackleton", -89.67, 129.78),
                                          ("Shoemaker", -88.14, 44.91),
                                          ("Cabeus", -85.33, -42.13)])
def test_known_craters_are_deep_and_not_mirrored(dem, name, lat, lon):
    """Crater floors sit far below the same latitude at the mirrored longitude."""
    h = float(dem.height_m(lat, lon))
    assert h < -2000 and h < float(dem.height_m(lat, -lon)) - 1000


def test_shackleton_floor_is_permanently_shadowed():
    r = analyze_site({"site": {"lat_deg": -89.67, "lon_deg_east": 129.78}, "engine": "spice",
                      "start_utc": "2027-01-01T00:00:00Z", "duration_days": 120,
                      "step_minutes": 240, "horizon_profile_id": "lola",
                      "include_time_series": False})
    assert r.summary.sun_visible_fraction_terrain == 0.0 and r.data_status == "REAL"


def test_connecting_ridge_is_mostly_sunlit():
    """Published LOLA studies: ridge near 89.45S 137.3W sunlit ~80-90% of a year."""
    r = analyze_site({"site": {"lat_deg": -89.45, "lon_deg_east": -137.3}, "engine": "spice",
                      "start_utc": "2027-01-01T00:00:00Z", "duration_days": 365,
                      "step_minutes": 240, "horizon_profile_id": "lola",
                      "visibility_definition": "upper_limb", "include_time_series": False})
    assert 0.7 < r.summary.sun_visible_fraction_terrain < 0.95
    assert r.horizon.data_status == "REAL" and r.horizon.details["site_height_m"] > 1500


def test_horizon_profile_shape_and_details():
    prof, diag = lola_horizon(-86.0, 0.0, "site_A")
    assert len(prof.azimuth_deg) == 360 and prof.data_status == "REAL"
    assert prof.source.startswith("NASA LRO LOLA LDEM_75S_240M")
    assert diag["min_ray_coverage_m"] >= 199_000 and 4000 < diag["site_height_m"] < 5500


def test_outside_coverage_rejected():
    with pytest.raises(TerrainError) as e:
        lola_horizon(-60.0, 0.0)
    assert e.value.code == "OUT_OF_COVERAGE"


def test_label_parser_on_saved_label():
    label = parse_label((FIXTURES / "ldem_75s_240m.lbl").read_text(encoding="latin-1"))
    assert label["LINES"] == 3812 and label["SAMPLE_TYPE"] == "LSB_INTEGER"
