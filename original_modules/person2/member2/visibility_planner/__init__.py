"""LUNA NAV AI - Member 02: Solar & Earth Visibility Planner.

Python interface (documented function contract):
    from visibility_planner import analyze_site, compare_windows
    result = analyze_site({"site": {"site_id": "site_A", "lat_deg": -86.0, "lon_deg_east": 0.0},
                           "start_utc": "2026-11-15T00:00:00Z", "duration_days": 7})
    payload = result.model_dump(mode="json")      # dict matching API_CONTRACT.md

Data: live NASA/JPL Horizons API by default (nothing to download); pass "engine": "spice" to use
local NASA NAIF kernels, or "auto" for Horizons with SPICE fallback.

REST interface: ``uvicorn visibility_planner.api:app --port 8002`` (see API_CONTRACT.md).
CLI: ``python -m visibility_planner --help``.
"""
from .horizon import HorizonProfile, flat_horizon, synthetic_profile
from .kernels import KernelError, kernels_available, load_kernels
from .models import (SCHEMA_VERSION, ComparisonResult, CompareRequest, ErrorResponse,
                     MissionWindow, SiteInput, VisibilityRequest, VisibilityResult)
from .planner import analyze_site, compare_windows, load_mock_response
from .sources import HorizonsSource, SpiceSource, UpstreamError

__version__ = "1.2.0"

__all__ = [
    "analyze_site", "compare_windows", "load_mock_response", "load_kernels", "kernels_available",
    "KernelError", "HorizonProfile", "flat_horizon", "synthetic_profile", "SCHEMA_VERSION",
    "VisibilityRequest", "VisibilityResult", "CompareRequest", "ComparisonResult",
    "MissionWindow", "SiteInput", "ErrorResponse", "UpstreamError", "HorizonsSource",
    "SpiceSource", "__version__",
]
