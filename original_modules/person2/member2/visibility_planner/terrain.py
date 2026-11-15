"""Terrain horizon profiles computed from an elevation model (default: NASA LRO LOLA).

For each azimuth we walk outward from the site along the great circle, read the terrain height
at each step, and convert every point to an elevation angle seen from the observer, exactly on
the sphere (Moon curvature included, no refraction: the Moon has no atmosphere):

    observer radius rs = R + h_site + mast_height,  target radius rt = R + h(d)
    theta = d / R (angular distance)
    elevation = atan2(rt*cos(theta) - rs, rt*sin(theta))

The horizon at that azimuth is the maximum elevation along the ray. Works with any DEM object
exposing ``height_m(lat_deg, lon_deg) -> meters above the 1737.4 km sphere`` (NaN = no data).
"""
from __future__ import annotations

from typing import Protocol

import numpy as np
from numpy.typing import ArrayLike, NDArray

from .frames import MOON_RADIUS_KM
from .horizon import HorizonProfile

R_M = MOON_RADIUS_KM * 1000.0


class DEM(Protocol):
    def height_m(self, lat_deg: ArrayLike, lon_deg: ArrayLike) -> NDArray[np.float64]: ...


def destination(lat_deg: float, lon_deg: float, az_deg: ArrayLike, dist_m: ArrayLike
                ) -> tuple[NDArray, NDArray]:
    """Great-circle destination from (lat, lon) along azimuth (clockwise from north) for dist_m."""
    phi1, lam1 = np.radians(lat_deg), np.radians(lon_deg)
    az = np.radians(np.asarray(az_deg, dtype=float))
    th = np.asarray(dist_m, dtype=float) / R_M
    sin_phi2 = np.sin(phi1) * np.cos(th) + np.cos(phi1) * np.sin(th) * np.cos(az)
    phi2 = np.arcsin(np.clip(sin_phi2, -1, 1))
    lam2 = lam1 + np.arctan2(np.sin(az) * np.sin(th) * np.cos(phi1),
                             np.cos(th) - np.sin(phi1) * sin_phi2)
    return np.degrees(phi2), (np.degrees(lam2) + 180.0) % 360.0 - 180.0


def elevation_angle_deg(h_obs_m: ArrayLike, h_target_m: ArrayLike, dist_m: ArrayLike) -> NDArray:
    """Elevation angle of a terrain point seen from the observer, exact spherical geometry."""
    th = np.asarray(dist_m, dtype=float) / R_M
    rs = R_M + np.asarray(h_obs_m, dtype=float)
    rt = R_M + np.asarray(h_target_m, dtype=float)
    return np.degrees(np.arctan2(rt * np.cos(th) - rs, rt * np.sin(th)))


def compute_horizon(dem: DEM, lat_deg: float, lon_deg: float, *, site_id: str = "site",
                    observer_height_m: float = 2.0, max_range_m: float = 200_000.0,
                    step_m: float = 120.0, az_step_deg: float = 1.0,
                    data_status: str = "REAL", source: str = "DEM",
                    profile_id: str | None = None) -> tuple[HorizonProfile, dict]:
    """Horizon profile (deg) at 0..360 by az_step_deg, plus diagnostics.

    The observer stands ``observer_height_m`` above the DEM surface at the site (e.g. a lander
    camera/antenna/solar panel height). Distances start at ``step_m`` and stop at ``max_range_m``
    or where the DEM has no data (NaN). Rays that run out of data early are reported.
    """
    h_site = float(dem.height_m(lat_deg, lon_deg))
    if not np.isfinite(h_site):
        raise ValueError(f"no DEM data at the site ({lat_deg}, {lon_deg})")
    az = np.arange(0.0, 360.0, az_step_deg)
    dist = np.arange(step_m, max_range_m + step_m / 2, step_m)
    A, D = np.meshgrid(az, dist, indexing="ij")                    # (n_az, n_dist)
    plat, plon = destination(lat_deg, lon_deg, A, D)
    h = dem.height_m(plat, plon)
    h_obs = h_site + observer_height_m
    el = elevation_angle_deg(h_obs, h, D)
    el = np.where(np.isfinite(h), el, -np.inf)
    k = np.argmax(el, axis=1)
    horizon = el[np.arange(az.size), k]
    covered = np.isfinite(h).sum(axis=1) * step_m
    if not np.all(np.isfinite(horizon)):
        raise ValueError("DEM has no data around the site")
    prof = HorizonProfile(
        site_id=site_id, profile_id=profile_id, data_status=data_status,  # type: ignore[arg-type]
        source=source, azimuth_deg=[float(a) for a in az],
        elevation_deg=[round(float(e), 4) for e in horizon])
    diag = {
        "site_height_m": round(h_site, 1),
        "observer_height_m": observer_height_m,
        "max_range_m": max_range_m, "step_m": step_m, "az_step_deg": az_step_deg,
        "horizon_distance_m": [round(float(dist[i]), 0) for i in k],
        "min_ray_coverage_m": float(covered.min()),
        "horizon_el_min_deg": round(float(horizon.min()), 4),
        "horizon_el_max_deg": round(float(horizon.max()), 4),
    }
    return prof, diag


def lola_horizon(lat_deg: float, lon_deg: float, site_id: str = "site",
                 observer_height_m: float = 2.0, max_range_m: float = 200_000.0,
                 lola_dir: str | None = None) -> tuple[HorizonProfile, dict]:
    """REAL horizon profile from NASA LOLA LDEM_75S_240M (south of 75 S only)."""
    from .lola import LolaDEM, TerrainError
    dem = LolaDEM.open(lola_dir)
    if lat_deg > dem.max_lat_deg:
        raise TerrainError(f"site latitude {lat_deg} is outside LOLA {dem.path.stem} coverage "
                           f"(south of {dem.max_lat_deg} deg only)", code="OUT_OF_COVERAGE")
    step = dem.scale_m / 2.0
    prof, diag = compute_horizon(
        dem, lat_deg, lon_deg, site_id=site_id, observer_height_m=observer_height_m,
        max_range_m=max_range_m, step_m=step, data_status="REAL", source=dem.source_text(),
        profile_id=f"lola_{dem.path.stem}")
    diag["dem"] = dem.path.stem.upper()
    return prof, diag
