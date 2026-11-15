from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from .models import AnalyzeResponse, Candidate, MissionRequest
from .service import analyze, get_site

app = FastAPI(title="LUNA NAV AI — Landing Site Analyzer", version="0.1.0",
              description="Terrain-only lunar landing site screening. No landing safety certification.")


@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, dict) else {"code": "http_error", "message": str(exc.detail)}
    return JSONResponse(status_code=exc.status_code, content={"data_status": "UNAVAILABLE", "error": detail})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"data_status": "UNAVAILABLE", "error": {"code": "validation_error", "message": "Request validation failed.",
        "details": [{"field": ".".join(str(part) for part in item["loc"]), "message": item["msg"]} for item in exc.errors()]}})


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"data_status": "UNAVAILABLE", "error": {"code": "internal_error", "message": "The request could not be completed."}})


@app.get("/api/v1/health")
def health():
    # Report what a request would actually use: the configured NASA LOLA DEM (REAL) or the synthetic grid (MOCK).
    import os
    img, lbl = os.getenv("LUNA_DEM_PATH"), os.getenv("LUNA_DEM_LABEL_PATH")
    real = bool(img and lbl and os.path.isfile(img) and os.path.isfile(lbl))
    return {"status": "ok", "module": "landing_site_analyzer", "api_version": "v1",
            "data_status": "REAL" if real else "MOCK", "dem": os.path.basename(img) if real else None}


@app.get("/api/v1/info")
def info():
    return {"module": "landing_site_analyzer", "version": "0.1.0", "body": "Moon", "data_status": "UNAVAILABLE",
            "capabilities": ["elevation", "local_slope", "local_roughness", "dynamic_candidate_generation", "terrain_ranking"],
            "coordinate_reference": "MEAN_EARTH_POLAR_AXIS", "coordinate_units": "degrees",
            "terrain_units": {"elevation": "m", "slope": "degrees", "roughness": "m"},
            "does_not_compute": ["solar_illumination", "earth_visibility", "mission_multi_objective_optimization"]}


@app.post("/api/v1/landing-sites/analyze", response_model=AnalyzeResponse)
def analyze_mission(payload: MissionRequest):
    try:
        return analyze(payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail={"code": "terrain_data_unavailable", "message": str(exc)}) from exc


@app.post("/api/v1/landing-sites/candidates", response_model=AnalyzeResponse)
def candidates(payload: MissionRequest):
    return analyze_mission(payload)


@app.get("/api/v1/landing-sites/{site_id}", response_model=Candidate)
def landing_site(site_id: str):
    candidate = get_site(site_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail={"code": "site_not_found", "message": "Unknown site_id; analyze a mission first."})
    return candidate
