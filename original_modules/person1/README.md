# LUNA NAV AI — Person 01: Landing Site Analyzer

Independent terrain screening service for lunar landing site candidates. It generates candidate coordinates dynamically from a requested region, samples elevation, estimates local slope and roughness, applies mission constraints, and returns ranked results with provenance. It does not calculate lighting, Earth visibility, or final multi-objective mission choices, and it does not certify landing safety.

## Install and run

Python 3.11 or newer is recommended.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m landing_site_analyzer
```

API base URL: `http://127.0.0.1:8000/api/v1`. Interactive OpenAPI docs: `http://127.0.0.1:8000/docs`.

Without configuration, analysis uses deterministic `MOCK` terrain. For NASA LOLA PDS IMG data, set paths to a compatible cylindrical IMG and its detached PDS label before starting:

```powershell
$env:LUNA_DEM_PATH = "C:\data\ldem_16.img"
$env:LUNA_DEM_LABEL_PATH = "C:\data\ldem_16.lbl"
python -m landing_site_analyzer
```

The data reader uses dimensions, sample byte order, scale, and map resolution in the PDS label. It supports 16-bit integer IMG files in the LOLA mean-Earth simple-cylindrical frame. Keep the source label alongside the raster; an unlabelled raster is rejected.

Request `data_mode: "real"` to fail with HTTP 503 if NASA data is unavailable, `"mock"` to force the local synthetic fixture, or `"auto"` (default) to use configured data when valid and otherwise use labeled mock terrain.

## API example

```powershell
$body = @{
  mission_id = "mission_001"
  target_region = @{
    body = "Moon"
    coordinate_reference = "MEAN_EARTH_POLAR_AXIS"
    projection = "EQUIRECTANGULAR"
    bounds = @{ min_latitude_deg = -10; max_latitude_deg = 10; min_longitude_deg = 20; max_longitude_deg = 40 }
  }
  constraints = @{ max_slope_deg = 10; max_roughness_m = 2.0 }
  candidate_count = 25
  data_mode = "auto"
} | ConvertTo-Json -Depth 6
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/landing-sites/analyze -ContentType application/json -Body $body
```

See [API_CONTRACT.md](API_CONTRACT.md) for field-level contracts and [NEXT_MEMBER_START_HERE.md](NEXT_MEMBER_START_HERE.md) for team connection steps. Verified provenance and access caveats are in [DATA_SOURCES.md](DATA_SOURCES.md).

## Test

```powershell
python -m pytest -q
```

Tests use synthetic grids and temporary PDS-format fixtures. They do not claim that a full NASA dataset has been downloaded or analyzed.
