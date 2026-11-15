from fastapi.testclient import TestClient

from landing_site_analyzer.app import app

client = TestClient(app)


def payload(**overrides):
    body = {
        "mission_id": "mission_test",
        "target_region": {
            "body": "Moon",
            "coordinate_reference": "MEAN_EARTH_POLAR_AXIS",
            "projection": "EQUIRECTANGULAR",
            "bounds": {"min_latitude_deg": -20, "max_latitude_deg": 20,
                       "min_longitude_deg": 10, "max_longitude_deg": 30},
        },
        "constraints": {"max_slope_deg": 20, "max_roughness_m": 1000},
        "candidate_count": 9,
        "data_mode": "mock",
    }
    body.update(overrides)
    return body


def test_health_and_info_contract():
    assert client.get("/api/v1/health").json()["status"] == "ok"
    info = client.get("/api/v1/info").json()
    assert info["coordinate_reference"] == "MEAN_EARTH_POLAR_AXIS"


def test_mock_analysis_dynamic_candidates_and_units():
    response = client.post("/api/v1/landing-sites/analyze", json=payload())
    assert response.status_code == 200
    data = response.json()
    assert data["data_status"] == "MOCK"
    assert data["data_coverage"]["min_latitude_deg"] <= -20
    assert data["generated_at_utc"].endswith("Z")
    assert 1 <= len(data["candidates"]) <= 9
    candidate = data["candidates"][0]
    assert candidate["coordinates"]["reference_frame"] == "MEAN_EARTH_POLAR_AXIS"
    assert isinstance(candidate["terrain"]["elevation_m"], (int, float))
    assert candidate["data_confidence"] == "LOW"
    assert data["data_limitations"]
    assert candidate["rank"] == 1
    assert any("synthetic" in warning.lower() for warning in data["warnings"])


def test_candidate_alias_and_site_lookup():
    data = client.post("/api/v1/landing-sites/candidates", json=payload()).json()
    site_id = data["candidates"][0]["site_id"]
    got = client.get(f"/api/v1/landing-sites/{site_id}")
    assert got.status_code == 200
    assert got.json()["site_id"] == site_id


def test_invalid_request_uses_standard_error_envelope():
    response = client.post("/api/v1/landing-sites/analyze", json={"mission_id": "x"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_unknown_site_has_standard_error_envelope():
    response = client.get("/api/v1/landing-sites/not-a-site")
    assert response.status_code == 404
    assert response.json()["data_status"] == "UNAVAILABLE"
    assert response.json()["error"]["code"] == "site_not_found"


def test_real_mode_without_dem_returns_503(monkeypatch):
    monkeypatch.delenv("LUNA_DEM_PATH", raising=False)
    response = client.post("/api/v1/landing-sites/analyze", json=payload(data_mode="real"))
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "terrain_data_unavailable"


def test_pds_label_decoder_and_sampling(tmp_path):
    import numpy as np
    from landing_site_analyzer.terrain import load_pds_img, sample_terrain

    img = tmp_path / "tiny.img"
    label = tmp_path / "tiny.lbl"
    values = np.arange(12, dtype="<i2").reshape(3, 4)
    values.tofile(img)
    label.write_text('''PDS_VERSION_ID = PDS3\nOBJECT = IMAGE\nLINES = 3\nLINE_SAMPLES = 4\nSAMPLE_BITS = 16\nSAMPLE_TYPE = LSB_INTEGER\nSCALING_FACTOR = 0.5\nEND_OBJECT = IMAGE\nMAP_PROJECTION_TYPE = "SIMPLE CYLINDRICAL"\nMAP_RESOLUTION = 1 <pix/deg>\nCENTER_LATITUDE = 89.5 <deg>\nCENTER_LONGITUDE = 0.5 <deg>\nLINE_PROJECTION_OFFSET = 0\nSAMPLE_PROJECTION_OFFSET = 0\nCOORDINATE_SYSTEM_NAME = "MEAN EARTH/POLAR AXIS OF DE421"\nEND\n''')
    grid = load_pds_img(img, label)
    assert grid.real_data and grid.data_status == "REAL"
    assert grid.elevations_m[1, 1] == 2.5
    assert sample_terrain(grid, 89.5, 0.5) is not None


def test_invalid_pds_byte_length_rejected(tmp_path):
    from landing_site_analyzer.terrain import load_pds_img

    img = tmp_path / "bad.img"
    label = tmp_path / "bad.lbl"
    img.write_bytes(b"short")
    label.write_text('''OBJECT = IMAGE\nLINES = 2\nLINE_SAMPLES = 2\nSAMPLE_BITS = 16\nSAMPLE_TYPE = LSB_INTEGER\nEND_OBJECT = IMAGE\nMAP_PROJECTION_TYPE = "SIMPLE CYLINDRICAL"\nCOORDINATE_SYSTEM_NAME = "MEAN EARTH/POLAR AXIS"\nEND\n''')
    try:
        load_pds_img(img, label)
    except ValueError as exc:
        assert "byte length mismatch" in str(exc)
    else:
        raise AssertionError("invalid PDS file should fail validation")


def test_constraints_filter_candidates_and_report_violations():
    strict = payload()
    strict["constraints"] = {"max_slope_deg": 0.01, "max_roughness_m": 0.0001,
                             "min_elevation_m": 1000000}
    response = client.post("/api/v1/landing-sites/analyze", json=strict)
    assert response.status_code == 200
    data = response.json()
    assert data["candidates"]
    assert all(c["constraint_violations"] for c in data["candidates"])
    assert any("No candidates met" in warning for warning in data["warnings"])


def test_terrain_derivatives_are_finite_and_nonnegative():
    import numpy as np
    from landing_site_analyzer.terrain import TerrainGrid, sample_terrain

    values = np.tile(np.arange(9, dtype=np.float32), (9, 1)) * 100.0
    grid = TerrainGrid(values, 1.0, "test ramp", "test", None, "fixture", "MOCK", False,
                       north_latitude_center_deg=4.0, west_longitude_center_deg=4.0)
    sampled = sample_terrain(grid, 0.0, 8.0)
    assert sampled is not None
    elevation, slope, roughness = sampled
    assert elevation == 400.0
    assert 0 < slope < 90
    assert roughness > 0
