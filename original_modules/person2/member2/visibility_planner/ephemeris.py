"""Sun and Earth apparent azimuth/elevation from a lunar surface site, via NASA SPICE.

An "ephemeris" is a table of where bodies are over time; here it is NASA JPL's DE440s.
Method: ``spiceypy.spkcpo`` with the site as a constant-position observer on body MOON in the
body-fixed frame, aberration correction ``LT+S``: light time (we see the Sun where it was
~8.3 min ago) plus stellar aberration (the observer's motion tilts incoming light). This
reproduces JPL Horizons' apparent az/el (verified to < 1e-5 deg, see TEST_REPORT.md).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import spiceypy as sp
from numpy.typing import NDArray

from .frames import MOON_RADIUS_KM, site_vector_km, to_az_el
from .kernels import SPICE_LOCK, ensure_loaded

ABERRATION = "LT+S"
TARGETS = {"sun": "SUN", "earth": "EARTH"}


@dataclass
class BodyTrack:
    """Apparent direction of one body at many epochs. Angles in degrees, range in km."""

    body: str
    az_deg: NDArray[np.float64]
    el_deg: NDArray[np.float64]
    range_km: NDArray[np.float64]
    angular_radius_deg: NDArray[np.float64]


def utc_to_et(utc_iso: str) -> float:
    """UTC ISO-8601 string ('...Z' accepted) -> ephemeris time (TDB seconds past J2000)."""
    ensure_loaded()
    with SPICE_LOCK:
        return float(sp.str2et(utc_iso.rstrip("Z")))


def et_to_utc(et: float) -> str:
    """Ephemeris time -> UTC ISO-8601 string with 'Z', whole seconds."""
    with SPICE_LOCK:
        return sp.et2utc(float(et), "ISOC", 0) + "Z"


def body_radius_km(body: str) -> float:
    """Mean of the three PCK radii of SUN or EARTH, km (from pck00011.tpc)."""
    with SPICE_LOCK:
        _, radii = sp.bodvrd(TARGETS[body], "RADII", 3)
    return float(np.mean(radii))


def body_track(body: str, ets: NDArray | list[float], lat_deg: float, lon_deg_east: float,
               alt_m: float = 0.0) -> BodyTrack:
    """Apparent az/el/range of 'sun' or 'earth' seen from the site at each ephemeris time."""
    frame = ensure_loaded()
    site = site_vector_km(lat_deg, lon_deg_east, alt_m, MOON_RADIUS_KM)
    ets = np.atleast_1d(np.asarray(ets, dtype=float))
    vecs = np.empty((ets.size, 3))
    with SPICE_LOCK:
        for i, et in enumerate(ets):
            state, _ = sp.spkcpo(TARGETS[body], float(et), frame, "OBSERVER", ABERRATION,
                                 site, "MOON", frame)
            vecs[i] = state[:3]
    rng = np.linalg.norm(vecs, axis=1)
    az, el = to_az_el(vecs, lat_deg, lon_deg_east)
    ang = np.degrees(np.arcsin(np.clip(body_radius_km(body) / rng, 0.0, 1.0)))
    return BodyTrack(body, np.atleast_1d(az), np.atleast_1d(el), rng, ang)


def sun_earth_az_el(lat_deg: float, lon_deg_east: float, times_utc: list[str],
                    alt_m: float = 0.0) -> dict[str, BodyTrack]:
    """Convenience wrapper: {'sun': BodyTrack, 'earth': BodyTrack} for UTC ISO strings."""
    ets = np.array([utc_to_et(t) for t in times_utc])
    return {b: body_track(b, ets, lat_deg, lon_deg_east, alt_m) for b in TARGETS}
