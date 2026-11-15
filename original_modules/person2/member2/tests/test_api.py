"""REST API integration tests via FastAPI TestClient (in-process HTTP)."""
import pytest
from fastapi.testclient import TestClient

from visibility_planner.api import API_PREFIX, app
from visibility_planner.models import ComparisonResult, ErrorResponse, VisibilityResult

client = TestClient(app)


def _assert_error(resp, status, code):
    assert resp.status_code == status, resp.text
    body = resp.json()
    ErrorResponse.model_validate(body)
    assert body["error"]["code"] == code and body["data_status"] == "UNAVAILABLE"
    return body


def test_health_and_meta():
    h = client.get("/health").json()
    assert h["module"] == "visibility_planner" and h["status"] in ("ok", "degraded")
    m = client.get(f"{API_PREFIX}/meta").json()
    assert m["conventions"]["angles"] == "degrees" and len(m["kernels"]) == 5
    assert "POST /api/v1/visibility/analyze" in m["endpoints"]


@pytest.mark.needs_kernels
def test_analyze_ok(base_request):
    r = client.post(f"{API_PREFIX}/analyze", json={**base_request, "horizon_profile_id": "ridge"})
    assert r.status_code == 200, r.text
    body = VisibilityResult.model_validate(r.json())
    assert body.data_status == "PARTIAL" and body.time_series


@pytest.mark.needs_kernels
def test_compare_ok(base_request):
    r = client.post(f"{API_PREFIX}/compare", json={
        "site": base_request["site"], "step_minutes": 60,
        "windows": [{"start_utc": "2026-11-15T00:00:00Z", "duration_days": 2},
                    {"start_utc": "2026-12-05T00:00:00Z", "duration_days": 2}]})
    assert r.status_code == 200, r.text
    c = ComparisonResult.model_validate(r.json())
    assert [w.label for w in c.windows] == ["window_1", "window_2"]


def test_validation_error_envelope(base_request):
    bad = {**base_request, "site": {"lat_deg": 120, "lon_deg_east": 0},
           "start_utc": "2026-11-15T00:00:00"}
    body = _assert_error(client.post(f"{API_PREFIX}/analyze", json=bad), 422, "VALIDATION_ERROR")
    fields = {d["field"] for d in body["error"]["details"]}
    assert "site.lat_deg" in fields and "start_utc" in fields


def test_malformed_json_is_422():
    r = client.post(f"{API_PREFIX}/analyze", content="{not json",
                    headers={"content-type": "application/json"})
    _assert_error(r, 422, "VALIDATION_ERROR")


def test_compare_needs_two_windows(base_request):
    r = client.post(f"{API_PREFIX}/compare", json={"site": base_request["site"], "windows": [
        {"start_utc": "2026-11-15T00:00:00Z", "duration_days": 1}]})
    _assert_error(r, 422, "VALIDATION_ERROR")


def test_kernels_unavailable_is_503(monkeypatch, tmp_path, base_request):
    from visibility_planner import kernels
    monkeypatch.setenv(kernels.KERNEL_DIR_ENV, str(tmp_path))
    monkeypatch.setitem(kernels._loaded, "frame", None)
    monkeypatch.setitem(kernels._loaded, "dir", None)
    body = _assert_error(client.post(f"{API_PREFIX}/analyze", json=base_request), 503,
                         "KERNELS_UNAVAILABLE")
    assert "fetch_kernels" in body["error"]["message"]
    h = client.get("/health").json()
    assert h["kernels_available"] is False and "spice" not in h["engines_available"]
    ok = client.post(f"{API_PREFIX}/analyze", json={**base_request, "use_mock": True})
    assert ok.status_code == 200 and ok.json()["data_status"] == "MOCK"


def test_horizon_profile_endpoints():
    lst = client.get(f"{API_PREFIX}/horizon-profiles").json()["profiles"]
    assert {p["profile_id"] for p in lst} == {"lola", "flat", "ridge", "crater_rim"}
    assert [p["data_status"] for p in lst if p["profile_id"] == "lola"] == ["REAL"]
    p = client.get(f"{API_PREFIX}/horizon-profiles/ridge?site_id=s1").json()
    assert p["data_status"] == "MOCK" and p["site_id"] == "s1" and len(p["azimuth_deg"]) == 360
    _assert_error(client.get(f"{API_PREFIX}/horizon-profiles/nope"), 404, "NOT_FOUND")


def test_unknown_profile_id_in_analyze_is_422(base_request):
    r = client.post(f"{API_PREFIX}/analyze", json={**base_request, "horizon_profile_id": "zzz"})
    _assert_error(r, 422, "VALIDATION_ERROR")


def test_mock_endpoints_are_labelled_mock():
    a = client.get(f"{API_PREFIX}/mock").json()
    VisibilityResult.model_validate(a)
    assert a["data_status"] == "MOCK" and "synthetic_fixture" in a["source"]
    c = client.get(f"{API_PREFIX}/mock?kind=compare").json()
    ComparisonResult.model_validate(c)
    assert c["data_status"] == "MOCK" and all(w["data_status"] == "MOCK" for w in c["windows"])


def test_openapi_lists_endpoints():
    paths = client.get("/openapi.json").json()["paths"]
    for p in ("/health", f"{API_PREFIX}/analyze", f"{API_PREFIX}/compare", f"{API_PREFIX}/mock"):
        assert p in paths


def test_horizons_unreachable_is_503(offline_horizons, base_request):
    req = {**base_request, "engine": "horizons"}
    body = _assert_error(client.post(f"{API_PREFIX}/analyze", json=req), 503, "UPSTREAM_UNAVAILABLE")
    assert "ssd.jpl.nasa.gov" in body["error"]["details"][0]["service"]
    assert client.get("/health?check_upstream=true").json()["status"] == "degraded"


@pytest.mark.needs_kernels
def test_auto_engine_falls_back_to_spice_when_offline(offline_horizons, base_request):
    r = client.post(f"{API_PREFIX}/analyze", json={**base_request, "engine": "auto"})
    assert r.status_code == 200, r.text
    ds = r.json()["data_source"]
    assert ds["engine"] == "spice" and "unreachable" in ds["fallback_reason"]


def test_horizons_rejecting_query_is_502(monkeypatch, base_request):
    import io
    import json as _json

    from visibility_planner import sources

    class Resp(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    sources.clear_cache()
    monkeypatch.setattr(sources.urllib.request, "urlopen", lambda *a, **k: Resp(
        _json.dumps({"result": "No ephemeris for target"}).encode()))
    r = client.post(f"{API_PREFIX}/analyze", json={**base_request, "engine": "horizons"})
    _assert_error(r, 502, "UPSTREAM_ERROR")
    sources.clear_cache()


@pytest.mark.needs_lola
def test_lola_profile_endpoint_and_analyze(base_request):
    p = client.get(f"{API_PREFIX}/horizon-profiles/lola?lat=-86&lon=0&site_id=s1").json()
    assert p["data_status"] == "REAL" and len(p["elevation_deg"]) == 360
    r = client.post(f"{API_PREFIX}/analyze", json={**base_request, "horizon_profile_id": "lola"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["data_status"] == "REAL" and body["horizon"]["profile_id"] == "lola_ldem_75s_240m"
    assert body["horizon"]["details"]["dem"] == "LDEM_75S_240M"


def test_lola_errors(monkeypatch, tmp_path, base_request):
    _assert_error(client.get(f"{API_PREFIX}/horizon-profiles/lola"), 422, "VALIDATION_ERROR")
    from visibility_planner import lola
    monkeypatch.setenv(lola.LOLA_DIR_ENV, str(tmp_path))
    monkeypatch.setenv(lola.AUTO_DOWNLOAD_ENV, "0")
    r = client.post(f"{API_PREFIX}/analyze", json={**base_request, "horizon_profile_id": "lola"})
    body = _assert_error(r, 503, "TERRAIN_UNAVAILABLE")
    assert "fetch_lola" in body["error"]["message"]


@pytest.mark.needs_lola
def test_lola_out_of_coverage_is_422(base_request):
    req = {**base_request, "site": {"lat_deg": -60, "lon_deg_east": 0}, "horizon_profile_id": "lola"}
    _assert_error(client.post(f"{API_PREFIX}/analyze", json=req), 422, "VALIDATION_ERROR")
