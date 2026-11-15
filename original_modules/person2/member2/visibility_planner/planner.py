"""Public Python interface: analyze_site() and compare_windows().

Both accept either the Pydantic request model or a plain dict with the same JSON shape, and
return Pydantic models (call ``.model_dump(mode="json")`` for JSON).

Data comes from NASA only:
  * engine "auto" (default): live NASA/JPL Horizons API; if it is unreachable and the NASA NAIF
    SPICE kernels are installed, the same computation runs offline from them;
  * engine "horizons": live Horizons only (error if unreachable);
  * engine "spice": offline NASA NAIF SPICE kernels only (scripts/fetch_kernels.py).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np

from .frames import MOON_RADIUS_KM
from .horizon import HorizonProfile, synthetic_profile
from .kernels import kernel_manifest, kernels_available
from .models import (ComparisonResult, CompareRequest, DataSourceInfo, HorizonInfo, KernelInfo,
                     Location, MissionWindow, SiteInput, Summary, TimeSeriesPoint,
                     VisibilityRequest, VisibilityResult, VisibilityWindow, WindowComparison,
                     iso_z)
from .sources import (EphemerisSource, HorizonsSource, Site, SpiceSource, Track, UpstreamError,
                      horizons_recently_failed)
from .windows import Interval, complement, find_windows, longest, total_duration

BODIES = ("sun", "earth")
MOCK_DIR = Path(__file__).resolve().parent / "mock_data"
SOURCE_TEXT = {
    "horizons": "NASA/JPL Horizons API (live observer ephemeris, MOON_ME/MEAN_ME)",
    "spice": "NASA NAIF SPICE (DE440s, MOON_ME)",
}

ASSUMPTIONS = [
    "Moon modelled as a sphere of radius 1737.4 km; site altitude is measured above it (meters).",
    "Coordinates: MOON_ME body-fixed frame (JPL Horizons calls it MEAN_ME), planetocentric "
    "latitude (south negative), east-positive longitude, degrees.",
    "Azimuth measured clockwise from local north (0..360 deg); elevation above the local "
    "horizontal plane tangent to the sphere.",
    "Apparent directions (light time + stellar aberration) from NASA/JPL Horizons, or identically "
    "from NASA NAIF SPICE spkcpo with LT+S when engine='spice'.",
    "No atmosphere, so no refraction on the Moon.",
    "Geometric visibility uses a smooth-sphere horizon (elevation 0). Terrain visibility uses "
    "the supplied horizon profile, interpolated linearly in azimuth with wrap-around.",
    "Sun and Earth are point directions plus an angular radius; partial illumination "
    "(penumbra) and Earth phase are not modelled.",
    "Samples are taken every step_minutes; rise/set times are refined to about 1 s. "
    "A rise and set both within one step would be missed.",
]


def _as(model: type, obj: Any) -> Any:
    return obj if isinstance(obj, model) else model.model_validate(obj)


def load_mock_response(name: str = "mock_visibility_response.json") -> dict[str, Any]:
    """The labelled MOCK example payload (data_status 'MOCK'), for consumers without data access."""
    return json.loads((MOCK_DIR / name).read_text(encoding="utf-8"))


_HORIZON_DETAILS: dict[int, dict] = {}


def resolve_horizon(site_id: str, profile: HorizonProfile | None, profile_id: str | None,
                    site: SiteInput | None = None, observer_height_m: float = 2.0
                    ) -> HorizonProfile | None:
    """Inline profile > 'lola' (REAL, computed at the site) > synthetic id > None (geometric)."""
    if profile is not None:
        return profile
    if profile_id == "lola":
        if site is None:
            raise ValueError("site required for a LOLA horizon")
        from .terrain import lola_horizon
        prof, diag = lola_horizon(site.lat_deg, site.lon_deg_east, site_id, observer_height_m)
        diag.pop("horizon_distance_m", None)
        _HORIZON_DETAILS[id(prof)] = diag
        return prof
    if profile_id is not None:
        return synthetic_profile(profile_id, site_id)
    return None


def make_source(engine: str, kernel_dir: str | Path | None = None) -> EphemerisSource:
    """Build the data source for 'horizons' | 'spice' | 'auto' (auto decides lazily, see _Auto)."""
    if engine == "spice":
        return SpiceSource(kernel_dir)
    if engine == "auto":
        return _AutoSource(kernel_dir)
    return HorizonsSource()


class _AutoSource:
    """Horizons first; on a network failure switch to SPICE kernels if they are installed.

    Fails over fast: one 15 s attempt per Horizons call, and for 2 minutes after a failure new
    requests go straight to SPICE (no repeated waiting while the network is down).
    """

    def __init__(self, kernel_dir: str | Path | None) -> None:
        self.kernel_dir = kernel_dir
        self.fallback_reason: str | None = None
        self.active: EphemerisSource = HorizonsSource(timeout_s=15.0, attempts=1)
        if horizons_recently_failed() and kernels_available(kernel_dir):
            self.active = SpiceSource(kernel_dir)
            self.fallback_reason = ("JPL Horizons was unreachable less than 2 minutes ago; "
                                    "using local NASA SPICE kernels")

    @property
    def engine(self) -> str:
        return self.active.engine

    def _call(self, name: str, *args: Any) -> Any:
        try:
            return getattr(self.active, name)(*args)
        except UpstreamError as e:
            if self.active.engine != "horizons" or e.reachable or not kernels_available(self.kernel_dir):
                raise
            self.fallback_reason = str(e)
            self.active = SpiceSource(self.kernel_dir)
            return getattr(self.active, name)(*args)

    def track(self, *args: Any) -> Track:
        return self._call("track", *args)

    def refine_crossing(self, *args: Any) -> datetime:
        return self._call("refine_crossing", *args)

    def info(self) -> dict:
        return {**self.active.info(), "fallback_reason": self.fallback_reason}


def _sample_times(start: datetime, end: datetime, step_min: float) -> list[datetime]:
    n = int(np.floor((end - start).total_seconds() / (step_min * 60.0) + 1e-9))
    times = [start + timedelta(minutes=step_min * k) for k in range(n + 1)]
    if times[-1] < end:
        times.append(end)
    return times


def _round_s(dt: datetime) -> datetime:
    return (dt + timedelta(microseconds=500_000)).replace(microsecond=0)


class _Computation:
    """All per-site, per-interval numbers for one analysis (internal)."""

    def __init__(self, source: EphemerisSource, site: SiteInput, start: datetime, end: datetime,
                 step_min: float, definition: str, horizon: HorizonProfile | None) -> None:
        self.src, self.horizon, self.limb = source, horizon, definition == "upper_limb"
        self.site = Site(site.lat_deg, site.lon_deg_east, site.alt_m)
        self.start = start
        self.utc = _sample_times(start, end, step_min)
        self.t = np.array([(x - start).total_seconds() for x in self.utc])
        self.tracks = {b: source.track(b, self.utc, self.site) for b in BODIES}
        self.geo: dict[str, list[Interval]] = {}
        self.ter: dict[str, list[Interval]] = {}
        for b in BODIES:
            self.geo[b] = find_windows(self.t, self._margin_of(self.tracks[b], False),
                                       refine_bracket=self._refiner(b, False))
            if horizon is not None:
                self.ter[b] = find_windows(self.t, self._margin_of(self.tracks[b], True),
                                           refine_bracket=self._refiner(b, True))

    def _margin_of(self, tr: Track, terrain: bool) -> np.ndarray:
        m = tr.el_deg + (tr.angular_radius_deg if self.limb else 0.0)
        if terrain and self.horizon is not None:
            m = m - self.horizon.elevation_at(tr.az_deg)
        return m

    def _refiner(self, body: str, terrain: bool):
        def f(t0: float, t1: float) -> float:
            tc = self.src.refine_crossing(body, self.at(t0), self.at(t1), self.site,
                                          lambda tr: self._margin_of(tr, terrain))
            return (tc - self.start).total_seconds()
        return f

    def at(self, t: float) -> datetime:
        return self.start + timedelta(seconds=float(t))

    # ------------------------------------------------------------------ derived products
    @property
    def span(self) -> float:
        return float(self.t[-1])

    def gaps(self, body: str, terrain: bool) -> list[Interval]:
        src = self.ter if terrain else self.geo
        return complement(src[body], 0.0, self.span)

    @staticmethod
    def _until_set(ws: list[Interval]) -> float | None:
        if ws and ws[0].starts_at_interval_start and not ws[0].ends_at_interval_end:
            return round(ws[0].end / 3600.0, 4)
        return None

    def summary(self) -> Summary:
        frac = lambda w: round(total_duration(w) / self.span, 6)  # noqa: E731
        hrs = lambda w: round(longest(w) / 3600.0, 4)  # noqa: E731
        ter = self.horizon is not None
        sun_el = self.tracks["sun"].el_deg
        return Summary(
            sun_visible_fraction=frac(self.geo["sun"]),
            earth_visible_fraction=frac(self.geo["earth"]),
            sun_visible_fraction_terrain=frac(self.ter["sun"]) if ter else None,
            earth_visible_fraction_terrain=frac(self.ter["earth"]) if ter else None,
            longest_dark_hours=hrs(self.gaps("sun", False)),
            longest_no_contact_hours=hrs(self.gaps("earth", False)),
            longest_dark_hours_terrain=hrs(self.gaps("sun", True)) if ter else None,
            longest_no_contact_hours_terrain=hrs(self.gaps("earth", True)) if ter else None,
            sun_elevation_max_deg=round(float(np.max(sun_el)), 4),
            sun_elevation_mean_deg=round(float(np.mean(sun_el)), 4),
            hours_until_sunset=self._until_set(self.geo["sun"]),
            hours_until_earthset=self._until_set(self.geo["earth"]),
            hours_until_sunset_terrain=self._until_set(self.ter["sun"]) if ter else None,
            hours_until_earthset_terrain=self._until_set(self.ter["earth"]) if ter else None,
        )

    def windows(self) -> list[VisibilityWindow]:
        out: list[VisibilityWindow] = []
        kinds = [("geometric", False)] + ([("terrain", True)] if self.horizon is not None else [])
        for kind, terrain in kinds:
            src = self.ter if terrain else self.geo
            groups = [("sun", src["sun"]), ("earth", src["earth"]),
                      ("dark", self.gaps("sun", terrain)), ("no_contact", self.gaps("earth", terrain))]
            for body, ivs in groups:
                out += [self._window(body, kind, iv) for iv in ivs]
        return out

    def _window(self, body: str, kind: str, iv: Interval) -> VisibilityWindow:
        return VisibilityWindow(
            body=body, kind=kind,  # type: ignore[arg-type]
            start_utc=iso_z(_round_s(self.at(iv.start))), end_utc=iso_z(_round_s(self.at(iv.end))),
            duration_hours=round(iv.duration / 3600.0, 4),
            starts_at_interval_start=iv.starts_at_interval_start,
            ends_at_interval_end=iv.ends_at_interval_end)

    def time_series(self) -> list[TimeSeriesPoint]:
        s, e = self.tracks["sun"], self.tracks["earth"]
        ms, me = self._margin_of(s, False), self._margin_of(e, False)
        ter = self.horizon is not None
        if ter:
            ts, te = self._margin_of(s, True), self._margin_of(e, True)
            hs, he = self.horizon.elevation_at(s.az_deg), self.horizon.elevation_at(e.az_deg)
        r4 = lambda x: round(float(x), 4)  # noqa: E731
        return [TimeSeriesPoint(
            utc=iso_z(self.utc[i]),
            sun_az_deg=r4(s.az_deg[i]), sun_el_deg=r4(s.el_deg[i]),
            earth_az_deg=r4(e.az_deg[i]), earth_el_deg=r4(e.el_deg[i]),
            sun_visible=bool(ms[i] > 0), earth_visible=bool(me[i] > 0),
            sun_visible_terrain=bool(ts[i] > 0) if ter else None,
            earth_visible_terrain=bool(te[i] > 0) if ter else None,
            sun_horizon_el_deg=r4(hs[i]) if ter else None,
            earth_horizon_el_deg=r4(he[i]) if ter else None,
        ) for i in range(len(self.utc))]


def _horizon_info(h: HorizonProfile | None) -> HorizonInfo:
    if h is None:
        return HorizonInfo(type="geometric", profile_id=None, data_status="REAL",
                           source="smooth sphere R=1737.4 km (no terrain)")
    return HorizonInfo(type="terrain", profile_id=h.profile_id or h.site_id,
                       data_status=h.data_status, source=h.source,
                       details=_HORIZON_DETAILS.get(id(h)))


def _status(h: HorizonProfile | None) -> str:
    """REAL with geometric or REAL terrain horizon; PARTIAL when the terrain part is MOCK."""
    return "REAL" if h is None or h.data_status == "REAL" else "PARTIAL"


def _source_text(engine: str, h: HorizonProfile | None) -> str:
    base = SOURCE_TEXT[engine]
    return base if h is None else f"{base}; horizon: {h.source} ({h.data_status})"


def _data_source(src: EphemerisSource) -> DataSourceInfo:
    return DataSourceInfo(**src.info(), accessed_utc=iso_z(datetime.now(timezone.utc)))


def _kernels(src: EphemerisSource) -> list[KernelInfo]:
    return [KernelInfo(**k) for k in kernel_manifest()] if src.engine == "spice" else []


def _frame(src: EphemerisSource) -> str:
    return getattr(getattr(src, "active", src), "frame", "") or "MOON_ME"


def _uncertainty(step_min: float, engine: str) -> dict[str, Any]:
    return {
        "az_el_horizons_vs_spice_deg": "max |diff| < 1e-6 deg over 174 reference rows "
                                       "(3 south-polar sites, Sun and Earth, 6 h steps, 7 days)",
        "engine": engine,
        "window_edge_refinement_s": 1.0,
        "sampling_step_minutes": step_min,
        "undetected_events": "rise+set pairs shorter than one sampling step can be missed",
        "terrain": "terrain results are only as good as the supplied horizon profile",
        "moon_shape": "smooth sphere; local topography enters only through the horizon profile",
    }


def analyze_site(request: VisibilityRequest | dict[str, Any],
                 kernel_dir: str | Path | None = None) -> VisibilityResult:
    """Sun/Earth time series + visibility windows for one site and interval.

    Raises:
        pydantic.ValidationError: invalid request.
        KeyError: unknown horizon_profile_id.
        UpstreamError: JPL Horizons unreachable or rejected the query (engine horizons/auto).
        KernelError: kernels missing (engine spice, or auto fallback without kernels).
    """
    req: VisibilityRequest = _as(VisibilityRequest, request)
    if req.use_mock:
        return VisibilityResult.model_validate(load_mock_response())
    horizon = resolve_horizon(req.site.site_id, req.horizon_profile, req.horizon_profile_id,
                              req.site, req.observer_height_m)
    src = make_source(req.engine, kernel_dir)
    c = _Computation(src, req.site, req.start_utc, req.end_utc, req.step_minutes,  # type: ignore[arg-type]
                     req.visibility_definition, horizon)
    return VisibilityResult(
        site_id=req.site.site_id, body_frame=_frame(src), moon_radius_km=MOON_RADIUS_KM,
        location=Location(lat_deg=req.site.lat_deg, lon_deg_east=req.site.lon_deg_east,
                          alt_m=req.site.alt_m),
        start_utc=iso_z(req.start_utc), end_utc=iso_z(req.end_utc),  # type: ignore[arg-type]
        step_minutes=req.step_minutes, visibility_definition=req.visibility_definition,
        horizon=_horizon_info(horizon), summary=c.summary(), windows=c.windows(),
        time_series=c.time_series() if req.include_time_series else [],
        assumptions=list(ASSUMPTIONS), uncertainty=_uncertainty(req.step_minutes, src.engine),
        kernels=_kernels(src), data_source=_data_source(src), mission=req.mission,
        generated_utc=iso_z(datetime.now(timezone.utc)),
        data_status=_status(horizon), source=_source_text(src.engine, horizon),  # type: ignore[arg-type]
    )


def compare_windows(request: CompareRequest | dict[str, Any],
                    kernel_dir: str | Path | None = None) -> ComparisonResult:
    """Same site, several candidate intervals: per-window summary numbers side by side.

    Reports numbers only. Ranking/recommendation is Member 04's job.
    """
    req: CompareRequest = _as(CompareRequest, request)
    if req.use_mock:
        return ComparisonResult.model_validate(load_mock_response("mock_compare_response.json"))
    horizon = resolve_horizon(req.site.site_id, req.horizon_profile, req.horizon_profile_id,
                              req.site, req.observer_height_m)
    src = make_source(req.engine, kernel_dir)
    rows: list[WindowComparison] = []
    for i, w in enumerate(req.windows):
        c = _Computation(src, req.site, w.start_utc, w.end_utc, req.step_minutes,  # type: ignore[arg-type]
                         req.visibility_definition, horizon)
        rows.append(WindowComparison(
            label=w.label or f"window_{i + 1}", start_utc=iso_z(w.start_utc),
            end_utc=iso_z(w.end_utc), duration_hours=round(c.span / 3600.0, 4),  # type: ignore[arg-type]
            summary=c.summary(), data_status=_status(horizon)))  # type: ignore[arg-type]
    table = {k: [getattr(r.summary, k) for r in rows] for k in Summary.model_fields}
    return ComparisonResult(
        site_id=req.site.site_id,
        location=Location(lat_deg=req.site.lat_deg, lon_deg_east=req.site.lon_deg_east,
                          alt_m=req.site.alt_m),
        body_frame=_frame(src), step_minutes=req.step_minutes,
        visibility_definition=req.visibility_definition, horizon=_horizon_info(horizon),
        windows=rows, table=table, data_source=_data_source(src), mission=req.mission,
        data_status=_status(horizon), source=_source_text(src.engine, horizon))  # type: ignore[arg-type]


__all__ = ["analyze_site", "compare_windows", "load_mock_response", "resolve_horizon",
           "make_source", "MissionWindow"]
