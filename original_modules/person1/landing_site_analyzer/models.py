from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_serializer, field_validator, model_validator


class DataStatus(str, Enum):
    REAL = "REAL"
    MOCK = "MOCK"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"


class Bounds(BaseModel):
    min_latitude_deg: float = Field(ge=-90, le=90, allow_inf_nan=False)
    max_latitude_deg: float = Field(ge=-90, le=90, allow_inf_nan=False)
    min_longitude_deg: float = Field(ge=-180, le=180, allow_inf_nan=False)
    max_longitude_deg: float = Field(ge=-180, le=180, allow_inf_nan=False)

    @model_validator(mode="after")
    def valid_bounds(self):
        if self.min_latitude_deg >= self.max_latitude_deg:
            raise ValueError("min_latitude_deg must be less than max_latitude_deg")
        if self.min_longitude_deg == self.max_longitude_deg:
            raise ValueError("longitude bounds must span a non-zero region")
        return self


class TargetRegion(BaseModel):
    body: Literal["Moon"] = "Moon"
    coordinate_reference: Literal["MEAN_EARTH_POLAR_AXIS"] = "MEAN_EARTH_POLAR_AXIS"
    projection: Literal["EQUIRECTANGULAR"] = "EQUIRECTANGULAR"
    bounds: Bounds


class Constraints(BaseModel):
    max_slope_deg: float = Field(default=10.0, gt=0, le=90, allow_inf_nan=False)
    max_roughness_m: float = Field(default=2.0, gt=0, allow_inf_nan=False)
    min_elevation_m: float | None = Field(default=None, allow_inf_nan=False)
    max_elevation_m: float | None = Field(default=None, allow_inf_nan=False)

    @model_validator(mode="after")
    def valid_elevation_range(self):
        if self.min_elevation_m is not None and self.max_elevation_m is not None and self.min_elevation_m > self.max_elevation_m:
            raise ValueError("min_elevation_m cannot exceed max_elevation_m")
        return self


class MissionRequest(BaseModel):
    mission_id: str = Field(min_length=1, max_length=100)
    mission_type: str = Field(default="lunar_landing", min_length=1, max_length=100)
    target_region: TargetRegion
    constraints: Constraints = Field(default_factory=Constraints)
    start_utc: datetime | None = None
    duration_days: float | None = Field(default=None, gt=0)
    candidate_count: int = Field(default=25, ge=1, le=500)
    data_mode: Literal["auto", "mock", "real"] = "auto"

    @field_validator("start_utc")
    @classmethod
    def utc_only(cls, value):
        if value is not None:
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("start_utc must include a UTC offset")
            if value.utcoffset().total_seconds() != 0:
                raise ValueError("start_utc must be expressed in UTC")
        return value


class Coordinates(BaseModel):
    latitude_deg: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude_deg: float = Field(ge=-180, le=180, allow_inf_nan=False)
    reference_frame: str = "MEAN_EARTH_POLAR_AXIS"


class Terrain(BaseModel):
    elevation_m: float = Field(allow_inf_nan=False)
    slope_deg: float = Field(ge=0, le=90, allow_inf_nan=False)
    roughness_m: float = Field(ge=0, allow_inf_nan=False)


class Candidate(BaseModel):
    site_id: str
    coordinates: Coordinates
    terrain: Terrain
    suitability_score: float = Field(ge=0, le=100)
    score_components: dict[str, float]
    rank: int = Field(ge=1)
    selection_reasons: list[str]
    constraint_violations: list[str]
    source: str
    resolution_m: float | None
    data_confidence: Literal["LOW", "MODERATE", "HIGH"]
    data_status: DataStatus


class SourceInfo(BaseModel):
    name: str
    provider: str
    url: str | None
    product_id: str | None


class AnalyzeResponse(BaseModel):
    mission_id: str
    module: str = "landing_site_analyzer"
    body: str = "Moon"
    generated_at_utc: datetime
    data_status: DataStatus
    data_sources: list[SourceInfo]
    data_resolution_m: float | None
    data_coverage: dict[str, float]
    data_limitations: list[str]
    coordinate_reference: str = "MEAN_EARTH_POLAR_AXIS"
    units: dict[str, str] = Field(default_factory=lambda: {"coordinates": "degrees", "elevation": "m", "distance": "m", "slope": "degrees", "roughness": "m"})
    candidates: list[Candidate]
    warnings: list[str] = Field(default_factory=list)

    @field_validator("generated_at_utc")
    @classmethod
    def timestamp_must_be_utc(cls, value):
        if value.tzinfo is None or value.utcoffset() is None or value.utcoffset().total_seconds() != 0:
            raise ValueError("generated_at_utc must be UTC")
        return value

    @field_serializer("generated_at_utc")
    def serialize_timestamp_as_z(self, value):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
