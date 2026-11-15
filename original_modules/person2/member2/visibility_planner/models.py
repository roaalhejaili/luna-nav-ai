"""Pydantic v2 models = the API contract of the visibility planner (schema_version 1.1).

1.1 (additive over 1.0): request ``engine``; result ``data_source``; summary
``sun_elevation_max_deg``, ``sun_elevation_mean_deg``, ``hours_until_sunset[_terrain]``,
``hours_until_earthset[_terrain]``; error codes ``UPSTREAM_UNAVAILABLE`` / ``UPSTREAM_ERROR``.

Conventions (shared by all LUNA NAV AI modules):
  * Timestamps: UTC, ISO-8601, always with a trailing 'Z' in outputs. Inputs must be
    timezone-aware ('Z' or '+00:00'); naive datetimes are rejected.
  * Angles and lunar coordinates: degrees. Latitude planetocentric, south negative;
    longitude east-positive, normalised to [-180, 180). Frame: MOON_ME.
  * Distances, heights, altitudes: meters. Durations: hours (float). Fractions: 0..1.
  * data_status: REAL | MOCK | PARTIAL | UNAVAILABLE. Never present MOCK data as REAL.
Fields may be ADDED in later minor versions; existing names, units and types will not change.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .horizon import DataStatus, HorizonProfile

SCHEMA_VERSION = "1.1"
MAX_SAMPLES = 50_000          # protects the service: duration / step must stay below this
MAX_DURATION_DAYS = 400.0

Body = Literal["sun", "earth", "dark", "no_contact"]
Kind = Literal["geometric", "terrain"]
VisibilityDefinition = Literal["center", "upper_limb"]
Engine = Literal["horizons", "spice", "auto"]


def iso_z(dt: datetime) -> str:
    """Format an aware datetime as 'YYYY-MM-DDTHH:MM:SSZ' in UTC."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _aware_utc(v: Any) -> datetime:
    if isinstance(v, str):
        v = datetime.fromisoformat(v.strip().replace("Z", "+00:00").replace("z", "+00:00"))
    if not isinstance(v, datetime):
        raise ValueError("must be an ISO-8601 datetime string")
    if v.tzinfo is None or v.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware UTC, e.g. '2026-11-15T00:00:00Z' "
                         "(naive datetimes are rejected)")
    return v.astimezone(timezone.utc)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ----------------------------------------------------------------------------- inputs
class SiteInput(_Strict):
    """A lunar surface location (MOON_ME, planetocentric, east-positive longitude)."""

    site_id: str = Field("site", min_length=1, max_length=100)
    lat_deg: float = Field(..., ge=-90.0, le=90.0, description="Latitude, deg, south negative.")
    lon_deg_east: float = Field(..., ge=-180.0, le=360.0,
                                description="East longitude, deg. Output normalised to [-180,180).")
    alt_m: float = Field(0.0, ge=-20_000.0, le=20_000.0,
                         description="Height above the 1737.4 km sphere, meters.")

    @field_validator("lon_deg_east")
    @classmethod
    def _norm_lon(cls, v: float) -> float:
        return (v + 180.0) % 360.0 - 180.0


class MissionWindow(_Strict):
    """Analysis interval. Give end_utc OR duration_days (not both)."""

    label: str | None = Field(None, max_length=100)
    start_utc: datetime
    end_utc: datetime | None = None
    duration_days: float | None = Field(None, gt=0, le=MAX_DURATION_DAYS)

    @field_validator("start_utc", "end_utc", mode="before")
    @classmethod
    def _aware(cls, v: Any) -> datetime | None:
        return None if v is None else _aware_utc(v)

    @model_validator(mode="after")
    def _resolve(self) -> "MissionWindow":
        if (self.end_utc is None) == (self.duration_days is None):
            raise ValueError("give exactly one of end_utc or duration_days")
        if self.end_utc is None:
            self.end_utc = self.start_utc + timedelta(days=self.duration_days)  # type: ignore[arg-type]
        if self.end_utc <= self.start_utc:
            raise ValueError("end_utc must be after start_utc")
        days = (self.end_utc - self.start_utc).total_seconds() / 86400
        if days > MAX_DURATION_DAYS:
            raise ValueError(f"interval longer than {MAX_DURATION_DAYS} days")
        self.duration_days = days
        return self


class MissionContext(BaseModel):
    """Optional shared mission metadata (team-wide mission input). Echoed back, not interpreted."""

    model_config = ConfigDict(extra="allow")
    mission_id: str | None = None
    mission_type: str | None = None
    target: str | None = None
    constraints: dict[str, Any] | None = Field(
        None, description="e.g. {'max_dark_hours': 50, 'max_no_contact_hours': 24}. Not evaluated here.")


class _AnalysisOptions(_Strict):
    step_minutes: float = Field(10.0, ge=0.5, le=1440.0, description="Sampling step, minutes.")
    visibility_definition: VisibilityDefinition = Field(
        "center", description="'center': disk centre above horizon (matches Horizons); "
                              "'upper_limb': any part of the disk above horizon.")
    horizon_profile: HorizonProfile | None = Field(
        None, description="Inline terrain horizon (e.g. from Member 01). Takes precedence.")
    horizon_profile_id: str | None = Field(
        None, description="'lola': REAL horizon computed at the site from NASA LRO LOLA "
                          "LDEM_75S_240M (sites south of 75 S). Synthetic MOCK profiles: "
                          "'flat' | 'ridge' | 'crater_rim'.")
    observer_height_m: float = Field(
        2.0, ge=0.0, le=100.0, description="For 'lola': height of the observer (camera, antenna, "
                                           "solar panel) above the local terrain, meters.")
    use_mock: bool = Field(False, description="Return the labelled MOCK example instead of computing.")
    engine: Engine = Field(
        "auto", description="'auto' (default): live NASA/JPL Horizons API, falling back to local "
                            "NASA NAIF SPICE kernels if Horizons is unreachable and kernels exist. "
                            "'horizons': live API only. 'spice': offline kernels only.")

    @model_validator(mode="after")
    def _one_horizon(self) -> "_AnalysisOptions":
        if self.horizon_profile is not None and self.horizon_profile_id is not None:
            raise ValueError("give horizon_profile OR horizon_profile_id, not both")
        return self


class VisibilityRequest(_AnalysisOptions):
    """Input of analyze_site / POST /api/v1/visibility/analyze."""

    site: SiteInput
    start_utc: datetime
    end_utc: datetime | None = None
    duration_days: float | None = Field(None, gt=0, le=MAX_DURATION_DAYS)
    include_time_series: bool = True
    mission: MissionContext | None = None

    @model_validator(mode="after")
    def _window(self) -> "VisibilityRequest":
        w = MissionWindow(start_utc=self.start_utc, end_utc=self.end_utc,
                          duration_days=self.duration_days)
        self.start_utc, self.end_utc, self.duration_days = w.start_utc, w.end_utc, w.duration_days
        n = self.duration_days * 1440.0 / self.step_minutes
        if n > MAX_SAMPLES:
            raise ValueError(f"too many samples ({n:.0f} > {MAX_SAMPLES}); increase step_minutes "
                             "or shorten the interval")
        return self

    @field_validator("start_utc", "end_utc", mode="before")
    @classmethod
    def _aware(cls, v: Any) -> datetime | None:
        return None if v is None else _aware_utc(v)

    def mission_window(self) -> MissionWindow:
        return MissionWindow(start_utc=self.start_utc, end_utc=self.end_utc)


class CompareRequest(_AnalysisOptions):
    """Input of compare_windows / POST /api/v1/visibility/compare."""

    site: SiteInput
    windows: list[MissionWindow] = Field(..., min_length=2, max_length=20)
    mission: MissionContext | None = None

    @model_validator(mode="after")
    def _limit(self) -> "CompareRequest":
        total = sum(w.duration_days or 0 for w in self.windows) * 1440.0 / self.step_minutes
        if total > MAX_SAMPLES:
            raise ValueError(f"too many samples in total ({total:.0f} > {MAX_SAMPLES})")
        return self


# ----------------------------------------------------------------------------- outputs
class Location(BaseModel):
    lat_deg: float
    lon_deg_east: float
    alt_m: float


class HorizonInfo(BaseModel):
    type: Kind
    profile_id: str | None = None
    data_status: Literal["REAL", "MOCK"]
    source: str
    details: dict[str, Any] | None = Field(
        None, description="For LOLA horizons: site terrain height, observer height, ray range, "
                          "horizon min/max (no per-azimuth arrays).")


class Summary(BaseModel):
    sun_visible_fraction: float = Field(..., ge=0, le=1)
    earth_visible_fraction: float = Field(..., ge=0, le=1)
    sun_visible_fraction_terrain: float | None = Field(None, ge=0, le=1)
    earth_visible_fraction_terrain: float | None = Field(None, ge=0, le=1)
    longest_dark_hours: float = Field(..., ge=0)
    longest_no_contact_hours: float = Field(..., ge=0)
    longest_dark_hours_terrain: float | None = Field(None, ge=0)
    longest_no_contact_hours_terrain: float | None = Field(None, ge=0)
    sun_elevation_max_deg: float | None = Field(None, description="Max Sun elevation over samples.")
    sun_elevation_mean_deg: float | None = Field(None, description="Mean Sun elevation over samples.")
    hours_until_sunset: float | None = Field(
        None, ge=0, description="Hours from start_utc to the first sunset (geometric). Null if the "
                                "Sun is down at start or does not set before end_utc.")
    hours_until_earthset: float | None = Field(
        None, ge=0, description="Hours from start_utc to the first Earthset (geometric); same rules.")
    hours_until_sunset_terrain: float | None = Field(None, ge=0)
    hours_until_earthset_terrain: float | None = Field(None, ge=0)


class VisibilityWindow(BaseModel):
    body: Body
    kind: Kind
    start_utc: str
    end_utc: str
    duration_hours: float = Field(..., ge=0)
    starts_at_interval_start: bool = Field(
        False, description="True if already in progress when the analysis interval began.")
    ends_at_interval_end: bool = Field(
        False, description="True if still in progress when the analysis interval ended.")


class TimeSeriesPoint(BaseModel):
    utc: str
    sun_az_deg: float
    sun_el_deg: float
    earth_az_deg: float
    earth_el_deg: float
    sun_visible: bool = Field(..., description="Geometric visibility (smooth sphere).")
    earth_visible: bool = Field(..., description="Geometric visibility (smooth sphere).")
    sun_visible_terrain: bool | None = None
    earth_visible_terrain: bool | None = None
    sun_horizon_el_deg: float | None = Field(None, description="Terrain horizon at Sun azimuth.")
    earth_horizon_el_deg: float | None = Field(None, description="Terrain horizon at Earth azimuth.")


class KernelInfo(BaseModel):
    name: str
    role: str
    url: str | None = None


class DataSourceInfo(BaseModel):
    """Which NASA data produced the numbers."""

    model_config = ConfigDict(extra="allow")
    engine: Literal["horizons", "spice", "mock"]
    name: str
    url: str | None = None
    ephemeris: str | None = None
    moon_frame: str | None = None
    requests: int = 0
    download_required: bool = False
    accessed_utc: str | None = None
    fallback_reason: str | None = Field(None, description="Set when engine 'auto' fell back to SPICE.")


class VisibilityResult(BaseModel):
    """Output of analyze_site / POST /api/v1/visibility/analyze."""

    schema_version: str = SCHEMA_VERSION
    module: str = "visibility_planner"
    site_id: str
    body_frame: str
    moon_radius_km: float
    location: Location
    start_utc: str
    end_utc: str
    step_minutes: float
    visibility_definition: VisibilityDefinition
    horizon: HorizonInfo
    summary: Summary
    windows: list[VisibilityWindow]
    time_series: list[TimeSeriesPoint]
    assumptions: list[str]
    uncertainty: dict[str, Any] = Field(default_factory=dict)
    kernels: list[KernelInfo] = Field(default_factory=list,
                                      description="SPICE kernels used (empty for engine 'horizons').")
    data_source: DataSourceInfo | None = None
    mission: MissionContext | None = None
    generated_utc: str | None = None
    data_status: DataStatus
    source: str

    @field_validator("start_utc", "end_utc")
    @classmethod
    def _z(cls, v: str) -> str:
        if not v.endswith("Z"):
            raise ValueError("UTC timestamps must end with 'Z'")
        return v


class WindowComparison(BaseModel):
    label: str
    start_utc: str
    end_utc: str
    duration_hours: float
    summary: Summary
    data_status: DataStatus


class ComparisonResult(BaseModel):
    """Output of compare_windows. Numbers side by side; NO ranking or recommendation."""

    schema_version: str = SCHEMA_VERSION
    module: str = "visibility_planner"
    site_id: str
    location: Location
    body_frame: str
    step_minutes: float
    visibility_definition: VisibilityDefinition
    horizon: HorizonInfo
    windows: list[WindowComparison]
    table: dict[str, list[float | None]] = Field(
        ..., description="Column-oriented copy of each summary metric, one value per window.")
    data_source: DataSourceInfo | None = None
    mission: MissionContext | None = None
    data_status: DataStatus
    source: str


class ErrorDetail(BaseModel):
    code: Literal["VALIDATION_ERROR", "KERNELS_UNAVAILABLE", "UPSTREAM_UNAVAILABLE",
                  "TERRAIN_UNAVAILABLE",
                  "UPSTREAM_ERROR", "NOT_FOUND", "COMPUTATION_ERROR", "INTERNAL_ERROR"]
    message: str
    details: list[dict[str, Any]] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    """Every non-2xx response of the REST API has exactly this shape."""

    error: ErrorDetail
    data_status: Literal["UNAVAILABLE"] = "UNAVAILABLE"
    module: str = "visibility_planner"
    schema_version: str = SCHEMA_VERSION
