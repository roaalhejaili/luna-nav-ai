"""Ephemeris data sources: where Sun/Earth azimuth/elevation come from.

* ``HorizonsSource`` (DEFAULT): live NASA/JPL Horizons API (https://ssd.jpl.nasa.gov/api/horizons.api),
  the ephemeris tool recommended by the Space Apps "Lunar Landing Site Navigator" challenge.
  Nothing to download. Observer on the Moon (``CENTER='coord@301'``), apparent az/el of the body
  centre in the high-precision Moon mean-Earth frame, airless, plus the body's angular diameter.
* ``SpiceSource``: offline NASA NAIF SPICE kernels (DE440s, MOON_ME), needs
  ``scripts/fetch_kernels.py`` once. Same numbers as Horizons to < 1e-6 deg.

Both return the same ``Track`` (degrees) on a UTC time grid and can locate a rise/set crossing
inside a bracket far more precisely than the sampling step.
"""
from __future__ import annotations

import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Callable, Protocol

import numpy as np
from numpy.typing import NDArray

HORIZONS_API = "https://ssd.jpl.nasa.gov/api/horizons.api"
HORIZONS_IDS = {"sun": "10", "earth": "399"}
USER_AGENT = "luna-nav-ai-visibility-planner/1.1"
J2000_JD = 2451545.0
J2000_UTC = datetime(2000, 1, 1, 12, tzinfo=timezone.utc)
REFINE_RESOLUTION_S = 10.0   # Horizons refinement: dense samples every <= 10 s, then linear interpolation


class UpstreamError(RuntimeError):
    """The online NASA data service could not be reached or returned an error.

    ``reachable`` is False for network failures (timeouts, DNS, HTTP 5xx), True when the service
    answered but rejected the query.
    """

    def __init__(self, message: str, reachable: bool = False) -> None:
        super().__init__(message)
        self.reachable = reachable


@dataclass
class Site:
    lat_deg: float
    lon_deg_east: float
    alt_m: float = 0.0


@dataclass
class Track:
    """Apparent direction of one body at several UTC epochs (all degrees)."""

    az_deg: NDArray[np.float64]
    el_deg: NDArray[np.float64]
    angular_radius_deg: NDArray[np.float64]


MarginOfTrack = Callable[[Track], NDArray[np.float64]]


class EphemerisSource(Protocol):
    engine: str

    def track(self, body: str, times: list[datetime], site: Site) -> Track: ...

    def refine_crossing(self, body: str, t0: datetime, t1: datetime, site: Site,
                        margin: MarginOfTrack) -> datetime: ...

    def info(self) -> dict: ...


def _utc(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc)


def jd_to_utc(jd: float) -> datetime:
    return J2000_UTC + timedelta(days=jd - J2000_JD)


def _hz_time(dt: datetime) -> str:
    """Horizons calendar time string with fractional seconds, UT."""
    dt = _utc(dt)
    return dt.strftime("%Y-%m-%d %H:%M:%S.") + f"{dt.microsecond // 1000:03d}"


def _interp_crossing(times: list[datetime], m: NDArray) -> datetime | None:
    """First sign change of margin m (positive = visible) along times, linearly interpolated."""
    vis = m > 0
    idx = np.nonzero(vis[1:] != vis[:-1])[0]
    if idx.size == 0:
        return None
    i = int(idx[0])
    frac = m[i] / (m[i] - m[i + 1]) if m[i] != m[i + 1] else 0.5
    return times[i] + (times[i + 1] - times[i]) * float(frac)


# ------------------------------------------------------------------------------------- Horizons
@lru_cache(maxsize=1024)
def _fetch(url: str, timeout: float, attempts: int = 3) -> str:
    """GET a Horizons API URL with retries; returns the 'result' text. Cached per URL."""
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                payload = json.loads(r.read().decode("utf-8"))
            if "error" in payload and "result" not in payload:
                raise UpstreamError(f"JPL Horizons rejected the query: {payload['error']}",
                                    reachable=True)
            return str(payload.get("result", ""))
        except UpstreamError:
            raise
        except urllib.error.HTTPError as e:
            if 400 <= e.code < 500:
                body = e.read().decode("utf-8", "replace")[:300]
                raise UpstreamError(f"JPL Horizons HTTP {e.code}: {body}", reachable=True) from e
            last = e
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
            last = e
        time.sleep(0.5 * (attempt + 1))
    note_horizons_failure()
    raise UpstreamError(f"JPL Horizons API unreachable ({HORIZONS_API}): {last}")


_last_failure: list[float] = [0.0]
FAILURE_MEMORY_S = 120.0


def note_horizons_failure() -> None:
    _last_failure[0] = time.monotonic()


def horizons_recently_failed(window_s: float = FAILURE_MEMORY_S) -> bool:
    """True if Horizons was unreachable within the last ``window_s`` seconds (circuit breaker)."""
    return _last_failure[0] > 0 and time.monotonic() - _last_failure[0] < window_s


def reset_failure_memory() -> None:
    _last_failure[0] = 0.0


def parse_horizons(result: str) -> tuple[NDArray, NDArray, NDArray, NDArray]:
    """Parse a Horizons OBSERVER CSV block with QUANTITIES='4,13' and CAL_FORMAT='JD'.

    Returns (jd_ut, az_deg, el_deg, angular_diameter_arcsec).
    """
    if "$$SOE" not in result or "$$EOE" not in result:
        msg = " ".join(result.strip().split())[:400]
        raise UpstreamError(f"JPL Horizons returned no ephemeris: {msg}", reachable=True)
    block = result.split("$$SOE", 1)[1].split("$$EOE", 1)[0]
    rows = []
    for line in block.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        nums = []
        for p in parts[1:]:
            try:
                nums.append(float(p))
            except ValueError:
                continue  # solar/lunar presence flags such as '*', 'i', 'm', ''
        if len(nums) < 3:
            raise UpstreamError(f"unexpected Horizons row: {line!r}", reachable=True)
        rows.append((float(parts[0]), nums[-3], nums[-2], nums[-1]))
    arr = np.array(rows, dtype=float).reshape(-1, 4)
    return arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3]


@dataclass
class HorizonsSource:
    """Live NASA/JPL Horizons API source (no downloads)."""

    timeout_s: float = 60.0
    attempts: int = 3
    engine: str = "horizons"
    requests_made: int = field(default=0, init=False)

    def _params(self, body: str, site: Site, start: datetime, stop: datetime, steps: int) -> dict:
        lon = site.lon_deg_east % 360.0
        return {
            "format": "json", "COMMAND": f"'{HORIZONS_IDS[body]}'", "OBJ_DATA": "'NO'",
            "MAKE_EPHEM": "'YES'", "EPHEM_TYPE": "'OBSERVER'", "CENTER": "'coord@301'",
            "COORD_TYPE": "'GEODETIC'",
            "SITE_COORD": f"'{lon:.6f},{site.lat_deg:.6f},{site.alt_m / 1000.0:.6f}'",
            "START_TIME": f"'{_hz_time(start)}'", "STOP_TIME": f"'{_hz_time(stop)}'",
            "STEP_SIZE": f"'{steps}'", "QUANTITIES": "'4,13'", "CSV_FORMAT": "'YES'",
            "ANG_FORMAT": "'DEG'", "TIME_TYPE": "'UT'", "CAL_FORMAT": "'JD'", "EXTRA_PREC": "'YES'",
        }

    def _query(self, body: str, site: Site, start: datetime, stop: datetime, steps: int) -> Track:
        """Equally spaced samples: steps+1 points from start to stop inclusive."""
        url = HORIZONS_API + "?" + urllib.parse.urlencode(self._params(body, site, start, stop, steps))
        misses = _fetch.cache_info().misses
        text = _fetch(url, self.timeout_s, self.attempts)
        self.requests_made += _fetch.cache_info().misses - misses
        jd, az, el, diam = parse_horizons(text)
        if jd.size != steps + 1:
            raise UpstreamError(f"Horizons returned {jd.size} rows, expected {steps + 1}",
                                reachable=True)
        return Track(az % 360.0, el, diam / 7200.0)

    def track(self, body: str, times: list[datetime], site: Site) -> Track:
        """Samples at ``times``, which must be a regular grid, optionally plus a final off-grid end."""
        if len(times) < 2:
            raise ValueError("need at least 2 times")
        step = times[1] - times[0]
        n = len(times) - 1
        tail: datetime | None = None
        if times[-1] - times[-2] != step:          # last point (interval end) is off-grid
            tail, n = times[-1], n - 1
        if n < 1:
            main = self._query(body, site, times[0], times[0] + step, 1)
            main = Track(main.az_deg[:1], main.el_deg[:1], main.angular_radius_deg[:1])
        else:
            main = self._query(body, site, times[0], times[n], n)
        if tail is None:
            return main
        end = self._query(body, site, tail, tail + timedelta(minutes=1), 1)
        return Track(np.append(main.az_deg, end.az_deg[0]), np.append(main.el_deg, end.el_deg[0]),
                     np.append(main.angular_radius_deg, end.angular_radius_deg[0]))

    def refine_crossing(self, body: str, t0: datetime, t1: datetime, site: Site,
                        margin: MarginOfTrack) -> datetime:
        """Dense re-sampling of [t0, t1] every <= 10 s, then linear interpolation of the margin."""
        steps = int(min(600, max(6, math.ceil((t1 - t0).total_seconds() / REFINE_RESOLUTION_S))))
        tr = self._query(body, site, t0, t1, steps)
        times = [t0 + (t1 - t0) * (k / steps) for k in range(steps + 1)]
        tc = _interp_crossing(times, margin(tr))
        return tc if tc is not None else t0 + (t1 - t0) / 2

    def info(self) -> dict:
        return {"engine": "horizons", "name": "NASA/JPL Horizons API (live)", "url": HORIZONS_API,
                "ephemeris": "JPL Horizons observer ephemeris (DE441), apparent az/el, airless",
                "moon_frame": "MEAN_ME high precision (= MOON_ME)", "requests": self.requests_made,
                "download_required": False}


def clear_cache() -> None:
    """Forget cached Horizons responses."""
    _fetch.cache_clear()


def horizons_reachable(timeout_s: float = 10.0) -> bool:
    """Cheap connectivity probe used by /health?check_upstream=true and the test suite."""
    try:
        req = urllib.request.Request(HORIZONS_API + "?format=json&COMMAND=%27MB%27&OBJ_DATA=%27NO%27&MAKE_EPHEM=%27NO%27",
                                     headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001 - any failure means "not reachable"
        return False


# ---------------------------------------------------------------------------------------- SPICE
@dataclass
class SpiceSource:
    """Offline NASA NAIF SPICE kernels (DE440s, MOON_ME)."""

    kernel_dir: str | Path | None = None
    engine: str = "spice"
    frame: str = field(default="", init=False)

    def __post_init__(self) -> None:
        from .kernels import load_kernels
        self.frame = load_kernels(self.kernel_dir)

    def track(self, body: str, times: list[datetime], site: Site) -> Track:
        from . import ephemeris as eph
        from .models import iso_z
        ets = [eph.utc_to_et(iso_z(t)) + _subsec(t) for t in times]
        tr = eph.body_track(body, ets, site.lat_deg, site.lon_deg_east, site.alt_m)
        return Track(tr.az_deg, tr.el_deg, tr.angular_radius_deg)

    def refine_crossing(self, body: str, t0: datetime, t1: datetime, site: Site,
                        margin: MarginOfTrack, tol_s: float = 0.5) -> datetime:
        """Bisection on the exact SPICE margin, to ``tol_s`` seconds."""
        m_lo = float(margin(self.track(body, [t0], site))[0])
        lo, hi = t0, t1
        while (hi - lo).total_seconds() > tol_s:
            mid = lo + (hi - lo) / 2
            mm = float(margin(self.track(body, [mid], site))[0])
            if (mm > 0) == (m_lo > 0):
                lo, m_lo = mid, mm
            else:
                hi = mid
        return lo + (hi - lo) / 2

    def info(self) -> dict:
        from .kernels import kernel_manifest
        return {"engine": "spice", "name": "NASA NAIF SPICE kernels (offline)",
                "url": "https://naif.jpl.nasa.gov/pub/naif/generic_kernels/",
                "ephemeris": "DE440s, LT+S aberration, apparent az/el, airless",
                "moon_frame": self.frame, "requests": 0, "download_required": True,
                "kernels": [k["name"] for k in kernel_manifest()]}


def _subsec(t: datetime) -> float:
    """Fractional seconds dropped by iso_z (whole-second formatting), re-added to ET."""
    return t.microsecond / 1e6
