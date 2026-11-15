"""Pure geometry: lunar site position and the local up/east/north (topocentric) frame.

Coordinate convention (shared with the whole LUNA NAV AI team):
  * Body-fixed frame: MOON_ME ("mean Earth / polar axis"): z = mean rotation pole,
    x = mean direction toward Earth. Its latitude/longitude grid is the one used by
    LOLA/LRO maps and NASA Moon Trek, and by JPL Horizons (MEAN_ME).
  * Planetocentric latitude in degrees, south negative, range [-90, 90].
  * Longitude in degrees, EAST positive.
  * Moon modelled as a sphere of radius 1737.4 km (IAU mean radius, the same value Horizons uses).
  * Azimuth: degrees clockwise from local north, in [0, 360). Elevation: degrees above the
    local horizontal plane (the plane tangent to the sphere), in [-90, 90].
No SPICE calls here; everything is NumPy and unit-testable.
"""
from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

MOON_RADIUS_KM: float = 1737.4


def site_vector_km(lat_deg: float, lon_deg_east: float, alt_m: float = 0.0,
                   radius_km: float = MOON_RADIUS_KM) -> NDArray[np.float64]:
    """Site position in the Moon body-fixed frame, km (sphere radius + altitude in meters)."""
    lat, lon = np.radians(lat_deg), np.radians(lon_deg_east)
    r = radius_km + alt_m / 1000.0
    return np.array([r * np.cos(lat) * np.cos(lon), r * np.cos(lat) * np.sin(lon), r * np.sin(lat)])


def topocentric_basis(lat_deg: float, lon_deg_east: float) -> tuple[NDArray, NDArray, NDArray]:
    """Unit vectors (up, east, north) at the site, expressed in the body-fixed frame.

    up = outward radial; east = (-sin lon, cos lon, 0); north = up x east.
    At the poles 'north' points along the given longitude's meridian, so azimuths there are
    relative to that meridian (same convention as Horizons).
    """
    lat, lon = np.radians(lat_deg), np.radians(lon_deg_east)
    up = np.array([np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)])
    east = np.array([-np.sin(lon), np.cos(lon), 0.0])
    north = np.cross(up, east)
    return up, east, north


def to_az_el(vectors: NDArray, lat_deg: float, lon_deg_east: float) -> tuple[NDArray, NDArray]:
    """Convert body-fixed direction vector(s) (shape (3,) or (N, 3)) to azimuth/elevation degrees.

    Returns (azimuth_deg in [0, 360), elevation_deg in [-90, 90]); scalars become 0-d arrays.
    """
    v = np.atleast_2d(np.asarray(vectors, dtype=float))
    v = v / np.linalg.norm(v, axis=1, keepdims=True)
    up, east, north = topocentric_basis(lat_deg, lon_deg_east)
    el = np.degrees(np.arcsin(np.clip(v @ up, -1.0, 1.0)))
    az = np.degrees(np.arctan2(v @ east, v @ north)) % 360.0
    if np.asarray(vectors).ndim == 1:
        return az[0], el[0]
    return az, el
