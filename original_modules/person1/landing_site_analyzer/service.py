from __future__ import annotations

import math
import os
import hashlib
from datetime import datetime, timezone

from .models import (AnalyzeResponse, Candidate, Coordinates, DataStatus, MissionRequest,
                     SourceInfo, Terrain)
from .terrain import TerrainGrid, load_pds_img, mock_grid, polar_local_highs, sample_terrain

_site_cache: dict[str, Candidate] = {}


def get_grid(mode: str) -> TerrainGrid:
    img = os.getenv("LUNA_DEM_PATH")
    label = os.getenv("LUNA_DEM_LABEL_PATH")
    if mode == "mock":
        return mock_grid()
    if img:
        try:
            return load_pds_img(img, label)
        except (OSError, ValueError) as exc:
            if mode == "real":
                raise RuntimeError(f"Configured NASA DEM could not be loaded: {exc}") from exc
            return mock_grid(f"Configured DEM could not be loaded: {exc}")
    if mode == "real":
        raise RuntimeError("No real DEM configured. Set LUNA_DEM_PATH and LUNA_DEM_LABEL_PATH")
    return mock_grid()


def analyze(request: MissionRequest) -> AnalyzeResponse:
    grid = get_grid(request.data_mode)
    bounds = request.target_region.bounds
    n = request.candidate_count
    lat_span = bounds.max_latitude_deg - bounds.min_latitude_deg
    # Explicitly support antimeridian-crossing longitude bounds.
    lon_span = (bounds.max_longitude_deg - bounds.min_longitude_deg) % 360.0
    if lon_span == 0:
        lon_span = 360.0
    rows = max(1, int(math.ceil(math.sqrt(n * lat_span / max(lon_span, 1e-6)))))
    cols = max(1, int(math.ceil(n / rows)))
    candidates: list[Candidate] = []
    data_confidence = "LOW" if grid.resolution_m >= 1000 else "MODERATE" if grid.resolution_m > 100 else "HIGH"
    # Default: regular lat/lon pattern. Opt-in (LUNA_P1_CANDIDATE_STRATEGY=elevated, polar DEM only):
    # local high ground on gentle slopes, which near the poles receives the most sunlight.
    elevated = grid.projection == "POLAR" and os.getenv("LUNA_P1_CANDIDATE_STRATEGY", "grid") == "elevated"
    if elevated:
        points = polar_local_highs(grid, bounds, request.constraints.max_slope_deg, n)
    else:
        points = [(bounds.min_latitude_deg + (ri + 0.5) * lat_span / rows,
                   (bounds.min_longitude_deg + (ci + 0.5) * lon_span / cols + 180) % 360 - 180)
                  for ri in range(rows) for ci in range(cols)]
    for lat, lon in points:
        terrain_values = sample_terrain(grid, lat, lon)
        if terrain_values is None:
            continue
        elevation, slope, roughness = terrain_values
        violations = []
        if slope > request.constraints.max_slope_deg:
            violations.append("slope_exceeds_maximum")
        if roughness > request.constraints.max_roughness_m:
            violations.append("roughness_exceeds_maximum")
        if request.constraints.min_elevation_m is not None and elevation < request.constraints.min_elevation_m:
            violations.append("elevation_below_minimum")
        if request.constraints.max_elevation_m is not None and elevation > request.constraints.max_elevation_m:
            violations.append("elevation_above_maximum")
        if request.constraints.min_elevation_m is not None or request.constraints.max_elevation_m is not None:
            elev_score = 100.0 if not any(v.startswith("elevation_") for v in violations) else 0.0
        else:
            elev_score = 100.0
        slope_score = max(0.0, 100 * (1 - slope / request.constraints.max_slope_deg))
        rough_score = max(0.0, 100 * (1 - roughness / request.constraints.max_roughness_m))
        score = 0.5 * slope_score + 0.3 * rough_score + 0.2 * elev_score
        if violations:
            # Retain rejected sites in the response for transparency; score reflects their measurements.
            pass
        reasons = ["low local terrain slope"] if slope_score >= 70 else []
        if rough_score >= 70:
            reasons.append("low local elevation variability")
        if elev_score == 100 and (request.constraints.min_elevation_m is not None or request.constraints.max_elevation_m is not None):
            reasons.append("elevation within configured mission range")
        if elevated:
            reasons.append("local high point within 1 km on gentle ground (higher polar terrain stays sunlit longer)")
        if not reasons:
            reasons.append("candidate generated within requested DEM coverage")
        coord_key = f"{lat:.5f},{lon:.5f}:{request.mission_id}"
        site_id = "site_" + hashlib.sha1(coord_key.encode()).hexdigest()[:12]
        candidate = Candidate(site_id=site_id,
            coordinates=Coordinates(latitude_deg=round(lat, 6), longitude_deg=round(lon, 6)),
            terrain=Terrain(elevation_m=round(elevation, 3), slope_deg=round(slope, 5), roughness_m=round(roughness, 3)),
            suitability_score=round(score, 3),
            score_components={"slope": round(slope_score, 3), "roughness": round(rough_score, 3), "elevation": round(elev_score, 3)},
            rank=1, selection_reasons=reasons, constraint_violations=violations,
            source=grid.source, resolution_m=round(grid.resolution_m, 3), data_confidence=data_confidence,
            data_status=DataStatus(grid.data_status))
        candidates.append(candidate)
        if len(candidates) >= n:
            break
    # Filter out violations for recommendation set. If none meet constraints return ranked measurements with violations.
    eligible = [c for c in candidates if not c.constraint_violations]
    ranked = sorted(eligible if eligible else candidates, key=lambda c: (-c.suitability_score, c.site_id))
    ranked = [c.model_copy(update={"rank": i + 1}) for i, c in enumerate(ranked)]
    for c in ranked:
        _site_cache[c.site_id] = c
    status = DataStatus(grid.data_status)
    if not candidates:
        status = DataStatus.UNAVAILABLE
    elif grid.real_data and len(candidates) < n:
        status = DataStatus.PARTIAL
    warnings = ["Terrain suitability is a screening aid; it does not certify landing safety.",
                "Sun illumination and Earth visibility are outside this module's scope."]
    if not grid.real_data:
        warnings.insert(0, "MOCK terrain is synthetic and is not a NASA measurement.")
        if grid.fallback_reason:
            warnings.insert(1, grid.fallback_reason)
    if not eligible and candidates:
        warnings.append("No candidates met every configured terrain constraint; returned sites have violations.")
    limitations = ["Slope and roughness are estimated from a local 3x3 raster window and inherit the input DEM scale.",
                   "The resolution-only data confidence class is not a statistical uncertainty estimate.",
                   "No geoid correction, illumination analysis, Earth visibility, or landing-hazard certification is performed."]
    if grid.resolution_m > 100:
        warnings.append("Input grid spacing is too coarse to resolve meter-scale landing hazards.")
    if not grid.real_data:
        limitations.insert(0, "Terrain values are deterministic synthetic fixture values, not lunar measurements.")
    for c in ranked:
        if status != c.data_status:
            c.data_status = status
    source = SourceInfo(name=grid.source, provider=grid.provider, url=grid.source_url, product_id=grid.product_id)
    min_lat = grid.north_latitude_center_deg - (grid.elevations_m.shape[0] - 0.5) / grid.pixels_per_degree
    max_lat = grid.north_latitude_center_deg + 0.5 / grid.pixels_per_degree
    if grid.projection == "POLAR":
        edge = grid.polar_limit_latitude_deg or 0.0
        min_lat, max_lat = (-90.0, edge) if grid.polar_hemisphere < 0 else (edge, 90.0)
        west_lon, east_lon = -180.0, 180.0
    elif grid.elevations_m.shape[1] / grid.pixels_per_degree >= 360.0:
        west_lon, east_lon = -180.0, 180.0
    else:
        west_lon = ((grid.west_longitude_center_deg - 0.5 / grid.pixels_per_degree + 180) % 360) - 180
        east_lon = ((grid.west_longitude_center_deg + (grid.elevations_m.shape[1] - 0.5) / grid.pixels_per_degree + 180) % 360) - 180
    return AnalyzeResponse(mission_id=request.mission_id, generated_at_utc=datetime.now(timezone.utc), data_status=status,
        data_sources=[source], data_resolution_m=round(grid.resolution_m, 3),
        data_coverage={"min_latitude_deg": round(min_lat, 6), "max_latitude_deg": round(max_lat, 6),
                       "west_longitude_deg": round(west_lon, 6), "east_longitude_deg": round(east_lon, 6)},
        data_limitations=limitations,
        candidates=ranked, warnings=warnings)


def get_site(site_id: str) -> Candidate | None:
    return _site_cache.get(site_id)
