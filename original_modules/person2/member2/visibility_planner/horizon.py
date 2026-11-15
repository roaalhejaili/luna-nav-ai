"""Local horizon profiles: how high the surrounding terrain rises at each azimuth.

On a perfectly smooth sphere the horizon is at elevation 0 everywhere ("geometric" visibility).
Real sites have crater rims and ridges, so a body can be above 0 deg and still hidden. A horizon
profile is a list of (azimuth_deg, elevation_deg) samples, interpolated linearly with
wrap-around at 360 -> 0 deg.

REAL horizon profiles will come from Member 01 (terrain module, LOLA elevation data). Until then
we ship three SYNTHETIC profiles, always labelled data_status "MOCK", source "synthetic_fixture".
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import numpy as np
from numpy.typing import ArrayLike, NDArray
from pydantic import BaseModel, ConfigDict, Field, model_validator

DataStatus = Literal["REAL", "MOCK", "PARTIAL", "UNAVAILABLE"]


class HorizonProfile(BaseModel):
    """Horizon elevation (deg) as a function of azimuth (deg clockwise from north).

    This is also the JSON exchange format with Member 01 (terrain).
    """

    model_config = ConfigDict(extra="ignore")

    site_id: str = Field(..., min_length=1, description="Site the profile belongs to.")
    data_status: DataStatus = Field(..., description="REAL if derived from measured terrain.")
    source: str = Field(..., min_length=1, description="Provenance, e.g. 'synthetic_fixture'.")
    azimuth_deg: list[float] = Field(..., min_length=2, description="Degrees, [0, 360).")
    elevation_deg: list[float] = Field(..., min_length=2, description="Degrees, [-90, 90].")
    profile_id: str | None = Field(None, description="Optional identifier of this profile.")

    @model_validator(mode="after")
    def _check(self) -> "HorizonProfile":
        if len(self.azimuth_deg) != len(self.elevation_deg):
            raise ValueError("azimuth_deg and elevation_deg must have the same length")
        az = np.asarray(self.azimuth_deg)
        el = np.asarray(self.elevation_deg)
        if not np.all(np.isfinite(az)) or not np.all(np.isfinite(el)):
            raise ValueError("horizon profile contains non-finite values")
        if np.any(az < 0) or np.any(az >= 360):
            raise ValueError("azimuth_deg values must be in [0, 360)")
        if np.any(np.abs(el) > 90):
            raise ValueError("elevation_deg values must be in [-90, 90]")
        if len(np.unique(az)) != len(az):
            raise ValueError("azimuth_deg values must be unique")
        if self.data_status not in ("REAL", "MOCK"):
            raise ValueError("horizon profile data_status must be REAL or MOCK")
        return self

    def elevation_at(self, azimuth_deg: ArrayLike) -> NDArray[np.float64]:
        """Horizon elevation (deg) at the given azimuth(s), linear with 360-degree wrap-around."""
        az = np.asarray(self.azimuth_deg)
        el = np.asarray(self.elevation_deg)
        order = np.argsort(az)
        return np.interp(np.asarray(azimuth_deg, dtype=float) % 360.0, az[order], el[order],
                         period=360.0)

    @classmethod
    def from_file(cls, path: str | Path) -> "HorizonProfile":
        """Load and validate a horizon profile JSON file."""
        return cls.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))


# --------------------------------------------------------------------------- synthetic profiles
_AZ = np.arange(0.0, 360.0, 1.0)


def _angdiff(a: NDArray, b: float) -> NDArray:
    """Smallest signed angle a - b in degrees, in [-180, 180)."""
    return (a - b + 180.0) % 360.0 - 180.0


def _bump(d: NDArray, half_width: float) -> NDArray:
    """Smooth cos^2 bump: 1 at d=0, 0 for |d| >= half_width."""
    return np.where(np.abs(d) < half_width, np.cos(np.pi * d / (2 * half_width)) ** 2, 0.0)


def _mock(site_id: str, profile_id: str, el: NDArray) -> HorizonProfile:
    return HorizonProfile(site_id=site_id, profile_id=profile_id, data_status="MOCK",
                          source="synthetic_fixture", azimuth_deg=[float(a) for a in _AZ],
                          elevation_deg=[round(float(e), 4) for e in el])


def flat_horizon(site_id: str = "any") -> HorizonProfile:
    """0 deg everywhere: identical to the geometric (smooth-sphere) case."""
    return _mock(site_id, "flat", np.zeros_like(_AZ))


def ridge_horizon(site_id: str = "any") -> HorizonProfile:
    """Smooth 3 deg ridge centred on north (az 0), 80 deg wide at the base, 0 elsewhere."""
    return _mock(site_id, "ridge", 3.0 * _bump(_angdiff(_AZ, 0.0), 40.0))


def crater_rim_horizon(site_id: str = "any") -> HorizonProfile:
    """Crater-rim style wall of 1 to 4 deg all around, with one gap (0 deg) centred on az 160."""
    wall = 2.5 + 1.5 * np.sin(np.radians(3 * _AZ))
    return _mock(site_id, "crater_rim", wall * (1.0 - _bump(_angdiff(_AZ, 160.0), 20.0)))


SYNTHETIC_PROFILES = {"flat": flat_horizon, "ridge": ridge_horizon, "crater_rim": crater_rim_horizon}


def synthetic_profile(profile_id: str, site_id: str = "any") -> HorizonProfile:
    """Return a built-in synthetic profile by id ('flat', 'ridge', 'crater_rim')."""
    if profile_id not in SYNTHETIC_PROFILES:
        raise KeyError(f"unknown horizon profile_id '{profile_id}'; "
                       f"available: {sorted(SYNTHETIC_PROFILES)}")
    return SYNTHETIC_PROFILES[profile_id](site_id)
