"""REST API (FastAPI) for the visibility planner. Contract: API_CONTRACT.md.

Run:  uvicorn visibility_planner.api:app --host 127.0.0.1 --port 8002
Docs: http://127.0.0.1:8002/docs (Swagger UI), OpenAPI JSON at /openapi.json.

Data: NASA/JPL Horizons API live by default (no download); SPICE kernels optional (engine "spice").

Environment:
  LUNA_SPICE_KERNEL_DIR  kernel folder for engine "spice"/"auto" (default <project>/data/spice_kernels)
  LUNA_CORS_ORIGINS      comma-separated allowed origins for browsers (default "*")
All errors use the ErrorResponse envelope: {"error": {"code", "message", "details"}, ...}.
"""
from __future__ import annotations

import os
from typing import Any, Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from . import __version__
from .frames import MOON_RADIUS_KM
from .horizon import SYNTHETIC_PROFILES, HorizonProfile, synthetic_profile
from .kernels import (KernelError, kernel_manifest, kernels_available, loaded_frame,
                      missing_kernels, resolve_kernel_dir)
from .models import (MAX_DURATION_DAYS, MAX_SAMPLES, SCHEMA_VERSION, ComparisonResult,
                     CompareRequest, ErrorDetail, ErrorResponse, VisibilityRequest,
                     VisibilityResult)
from .planner import ASSUMPTIONS, analyze_site, compare_windows, load_mock_response
from .lola import PRODUCT as LOLA_PRODUCT
from .lola import TerrainError, lola_dir
from .sources import HORIZONS_API, UpstreamError, horizons_reachable
from .terrain import lola_horizon

API_PREFIX = "/api/v1/visibility"

app = FastAPI(
    title="LUNA NAV AI - Visibility Planner (Member 02)",
    version=__version__,
    description="Sun/Earth elevation, azimuth and visibility windows for lunar surface sites, "
                "from the live NASA/JPL Horizons API (default) or NASA NAIF SPICE kernels. "
                "UTC ISO-8601 'Z', degrees, meters, MOON_ME frame.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.environ.get("LUNA_CORS_ORIGINS", "*").split(",")],
    allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["*"])

_ERR = {422: {"model": ErrorResponse}, 502: {"model": ErrorResponse},
        503: {"model": ErrorResponse}, 500: {"model": ErrorResponse}}


def _error(status: int, code: str, message: str, details: list[dict[str, Any]] | None = None
           ) -> JSONResponse:
    body = ErrorResponse(error=ErrorDetail(code=code, message=message, details=details or []))  # type: ignore[arg-type]
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"))


def _clean(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """JSON-safe validation details: field path, message, error type."""
    return [{"field": ".".join(str(p) for p in e.get("loc", ()) if p != "body") or "body",
             "message": str(e.get("msg", "")), "type": str(e.get("type", ""))} for e in errors]


@app.exception_handler(RequestValidationError)
async def _on_request_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
    return _error(422, "VALIDATION_ERROR", "Request body failed validation.", _clean(exc.errors()))


@app.exception_handler(ValidationError)
async def _on_validation(_: Request, exc: ValidationError) -> JSONResponse:
    return _error(422, "VALIDATION_ERROR", "Input failed validation.", _clean(exc.errors()))


@app.exception_handler(KernelError)
async def _on_kernels(_: Request, exc: KernelError) -> JSONResponse:
    return _error(503, "KERNELS_UNAVAILABLE", str(exc),
                  [{"hint": "run `python scripts/fetch_kernels.py`, or send \"use_mock\": true "
                            "to receive the labelled MOCK example"}])


@app.exception_handler(UpstreamError)
async def _on_upstream(_: Request, exc: UpstreamError) -> JSONResponse:
    if exc.reachable:
        return _error(502, "UPSTREAM_ERROR", str(exc), [{"service": HORIZONS_API}])
    return _error(503, "UPSTREAM_UNAVAILABLE", str(exc),
                  [{"service": HORIZONS_API,
                    "hint": "retry, use engine 'auto' or 'spice' with downloaded kernels, "
                            "or use_mock true for the labelled MOCK example"}])


@app.exception_handler(TerrainError)
async def _on_terrain(_: Request, exc: TerrainError) -> JSONResponse:
    if exc.code == "OUT_OF_COVERAGE":
        return _error(422, "VALIDATION_ERROR", str(exc), [{"field": "site.lat_deg"}])
    return _error(503, "TERRAIN_UNAVAILABLE", str(exc),
                  [{"hint": "run `python scripts/fetch_lola.py` (29 MB, NASA PDS) or use a "
                            "synthetic horizon_profile_id"}])


@app.exception_handler(KeyError)
async def _on_key(_: Request, exc: KeyError) -> JSONResponse:
    return _error(422, "VALIDATION_ERROR", str(exc.args[0]) if exc.args else "unknown key")


@app.exception_handler(Exception)
async def _on_any(_: Request, exc: Exception) -> JSONResponse:  # pragma: no cover - safety net
    return _error(500, "INTERNAL_ERROR", f"{type(exc).__name__}: {exc}")


@app.get("/health", tags=["meta"])
def health(check_upstream: bool = False) -> dict[str, Any]:
    """Liveness + readiness. Always 200.

    ``check_upstream=true`` pings JPL Horizons (the default engine). 'status' is 'ok' unless that
    check fails, then 'degraded' (only SPICE, if installed, and mock work).
    """
    k_ok = kernels_available()
    hz = horizons_reachable() if check_upstream else None
    return {"status": "degraded" if hz is False else "ok", "module": "visibility_planner",
            "version": __version__, "schema_version": SCHEMA_VERSION,
            "default_engine": "auto", "horizons_api": HORIZONS_API, "horizons_reachable": hz,
            "kernels_available": k_ok, "missing_kernels": missing_kernels(),
            "lola_dem_available": (lola_dir() / f"{LOLA_PRODUCT}.img").exists(),
            "kernel_dir": str(resolve_kernel_dir()), "body_frame_loaded": loaded_frame(),
            "engines_available": [e for e, ok in (("horizons", hz is not False), ("spice", k_ok),
                                                  ("mock", True)) if ok]}


@app.get(f"{API_PREFIX}/meta", tags=["meta"])
def meta() -> dict[str, Any]:
    """Conventions, limits, kernels and endpoint list: everything a client needs to integrate."""
    return {
        "module": "visibility_planner", "version": __version__, "schema_version": SCHEMA_VERSION,
        "conventions": {
            "time": "UTC ISO-8601 with trailing 'Z'; naive datetimes rejected",
            "angles": "degrees", "distances_heights": "meters", "durations": "hours",
            "body_frame": "MOON_ME (mean Earth / polar axis), spherical Moon R=1737.4 km",
            "latitude": "planetocentric, south negative, [-90, 90]",
            "longitude": "east-positive, output normalised to [-180, 180)",
            "azimuth": "clockwise from local north, [0, 360)",
            "elevation": "above local horizontal plane, [-90, 90]",
            "data_status": ["REAL", "MOCK", "PARTIAL", "UNAVAILABLE"],
        },
        "moon_radius_km": MOON_RADIUS_KM,
        "limits": {"max_samples": MAX_SAMPLES, "max_duration_days": MAX_DURATION_DAYS,
                   "step_minutes": [0.5, 1440]},
        "visibility_definitions": ["center", "upper_limb"],
        "engines": {"auto": "default; Horizons, falling back to local SPICE kernels if unreachable",
                    "horizons": f"live NASA/JPL Horizons API {HORIZONS_API} only, no download",
                    "spice": "offline NASA NAIF SPICE kernels only (scripts/fetch_kernels.py)"},
        "horizon_profiles": sorted(SYNTHETIC_PROFILES),
        "kernels": kernel_manifest(), "assumptions": ASSUMPTIONS,
        "endpoints": [f"GET /health", f"GET {API_PREFIX}/meta", f"POST {API_PREFIX}/analyze",
                      f"POST {API_PREFIX}/compare", f"GET {API_PREFIX}/horizon-profiles",
                      f"GET {API_PREFIX}/horizon-profiles/{{profile_id}}",
                      f"GET {API_PREFIX}/mock"],
    }


@app.post(f"{API_PREFIX}/analyze", response_model=VisibilityResult, responses=_ERR,
          tags=["visibility"])
def analyze(req: VisibilityRequest) -> VisibilityResult:
    """Time series + Sun/Earth/dark/no-contact windows for one site and interval."""
    return analyze_site(req)


@app.post(f"{API_PREFIX}/compare", response_model=ComparisonResult, responses=_ERR,
          tags=["visibility"])
def compare(req: CompareRequest) -> ComparisonResult:
    """Same site, 2..20 candidate intervals: summary numbers side by side (no ranking)."""
    return compare_windows(req)


@app.get(f"{API_PREFIX}/horizon-profiles", tags=["horizon"])
def list_profiles() -> dict[str, Any]:
    """Available horizon profiles: 'lola' (REAL, computed per site) + synthetic MOCK ones."""
    return {"profiles": [{"profile_id": "lola", "data_status": "REAL",
                          "source": "NASA LRO LOLA LDEM_75S_240M, computed for lat/lon "
                                    "(south of 75 S)", "requires": ["lat", "lon"]}]
            + [{"profile_id": k, "data_status": "MOCK", "source": "synthetic_fixture"}
               for k in sorted(SYNTHETIC_PROFILES)]}


@app.get(f"{API_PREFIX}/horizon-profiles/{{profile_id}}", response_model=HorizonProfile,
         responses={404: {"model": ErrorResponse}}, tags=["horizon"])
def get_profile(profile_id: str, site_id: str = "any", lat: float | None = None,
                lon: float | None = None, observer_height_m: float = 2.0) -> Any:
    """One horizon profile in the exchange format (HorizonProfile).

    'lola' needs ``lat`` and ``lon`` (south of 75 S) and returns a REAL profile from NASA LOLA.
    """
    if profile_id == "lola":
        if lat is None or lon is None or not (-90 <= lat <= 90) or not (0 <= observer_height_m <= 100):
            return _error(422, "VALIDATION_ERROR", "lola needs lat (deg) and lon (deg east)",
                          [{"field": "lat"}, {"field": "lon"}])
        prof, _ = lola_horizon(lat, lon, site_id, observer_height_m)
        return prof
    if profile_id not in SYNTHETIC_PROFILES:
        return _error(404, "NOT_FOUND", f"unknown profile_id '{profile_id}'",
                      [{"available": sorted(SYNTHETIC_PROFILES)}])
    return synthetic_profile(profile_id, site_id)


@app.get(f"{API_PREFIX}/mock", tags=["visibility"])
def mock(kind: Literal["analyze", "compare"] = "analyze") -> dict[str, Any]:
    """Labelled MOCK example (data_status 'MOCK') of an analyze or compare response."""
    name = "mock_visibility_response.json" if kind == "analyze" else "mock_compare_response.json"
    return load_mock_response(name)
