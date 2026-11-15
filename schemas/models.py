from __future__ import annotations
from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field, field_validator, model_validator

FRAME = 'IAU_MOON_2015: planetocentric latitude, east-positive longitude, mean Earth/polar axis'
Status = Literal['MOCK', 'VERIFIED', 'UNVERIFIED']

class Requirements(BaseModel):
    mission_type: str = 'science'
    request: str = ''
    dates_utc: list[datetime]
    duration_hours: float = Field(gt=0, le=8760)
    objectives: list[str] = Field(default_factory=list)
    priorities: dict[str, float] = Field(default_factory=lambda: {'terrain': 1, 'sunlight': 1, 'communication': 1, 'navigation': 0})
    constraints: dict[str, float] = Field(default_factory=lambda: {'max_slope_deg': 15, 'min_sunlight_hours': 0, 'max_blackout_hours': 72})
    require_navigation: bool = False
    allow_mock_recommendation: bool = True

    @field_validator('dates_utc')
    @classmethod
    def dates(cls, v):
        if not v or len(v) > 30 or any(x.tzinfo is None or x.utcoffset() is None for x in v):
            raise ValueError('Provide 1-30 timezone-aware UTC dates')
        return [x.astimezone(timezone.utc) for x in v]

    @model_validator(mode='after')
    def check(self):
        allowed = {'terrain', 'sunlight', 'communication', 'navigation'}
        if set(self.priorities) - allowed or any(v < 0 for v in self.priorities.values()) or sum(self.priorities.values()) <= 0:
            raise ValueError('Priorities must be nonnegative allowed weights with positive sum')
        keys = {'max_slope_deg', 'min_sunlight_hours', 'max_blackout_hours', 'max_route_m'}
        if set(self.constraints) - keys or any(v < 0 for v in self.constraints.values()):
            raise ValueError('Invalid constraints')
        return self

class Provenance(BaseModel):
    status: Status
    source: str = Field(min_length=1)
    observed_at_utc: datetime
    uncertainty: str | None = None

    @field_validator('observed_at_utc')
    @classmethod
    def utc_observation(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('Provenance timestamp must be timezone-aware')
        return value.astimezone(timezone.utc)

class Site(BaseModel):
    site_id: str
    name: str
    latitude_deg: float = Field(ge=-90, le=90)
    longitude_deg: float = Field(ge=0, lt=360)
    elevation_m: float
    slope_deg: float = Field(ge=0, le=90)
    coordinate_frame: Literal['IAU_MOON_2015: planetocentric latitude, east-positive longitude, mean Earth/polar axis'] = FRAME
    provenance: Provenance

class Visibility(BaseModel):
    site_id: str
    date_utc: datetime
    sunlight_hours: float = Field(ge=0)
    earth_visible_hours: float = Field(ge=0)
    max_blackout_hours: float = Field(ge=0)
    provenance: Provenance

    @field_validator('date_utc')
    @classmethod
    def utc_date(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('Visibility date must be timezone-aware')
        return value.astimezone(timezone.utc)

class Route(BaseModel):
    site_id: str
    distance_m: float = Field(ge=0)
    accessible: bool
    provenance: Provenance

class Option(BaseModel):
    site: Site
    visibility: Visibility
    route: Route | None = None
    feasible: bool
    violations: list[str]
    score: float | None = None
    explanation: str

class PlanResponse(BaseModel):
    mission_id: str
    requirements: Requirements
    candidates: list[Option]
    ranked_alternatives: list[Option]
    recommendation: Option | None
    warnings: list[str]
    limitations: list[str]
    generated_at_utc: datetime
    metrics: dict[str, float | int] = Field(default_factory=dict)
    ai_summary: str | None = None  # optional Gemini narrative, number-grounded
    llm_provider: str = 'none'

class ReplanRequest(BaseModel):
    previous: PlanResponse
    requirements: Requirements

class CompareRequest(BaseModel):
    requirements: Requirements

class CompareResponse(BaseModel):
    baseline: PlanResponse
    hybrid: PlanResponse
    metrics: dict[str, dict[str, float | int]]
