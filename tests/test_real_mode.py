"""Guards added for the NASA real-data mode (v8)."""
from fastapi.testclient import TestClient
from api.main import app
from orchestration import engine
from orchestration.engine import mock_limitations
from tools.member_adapters import Member3NavigationService

client = TestClient(app)
BASE = {'dates_utc': ['2030-01-01T00:00:00Z'], 'duration_hours': 48,
        'priorities': {'terrain': 1, 'sunlight': 1, 'communication': 1, 'navigation': 1}}


def test_required_navigation_without_target_fails_fast_with_422(monkeypatch):
    monkeypatch.setenv('LUNA_NAVIGATION_URL', 'http://127.0.0.1:9')  # never contacted
    monkeypatch.delenv('LUNA_NAV_TARGET_LAT', raising=False)
    monkeypatch.delenv('LUNA_NAV_TARGET_LON', raising=False)
    called = []
    original = engine.graph
    monkeypatch.setattr(engine, 'graph', lambda: called.append(1) or original())
    r = client.post('/mission/plan', json={**BASE, 'require_navigation': True})
    # Standard FastAPI 422 body ({"detail": str}); the UI's formatValidation shows it verbatim.
    assert r.status_code == 422 and 'LUNA_NAV_TARGET_LAT' in r.json()['detail']
    assert called == []  # no site/visibility work was started


def test_target_configured_helper(monkeypatch):
    monkeypatch.setenv('LUNA_NAV_TARGET_LAT', '-90'); monkeypatch.setenv('LUNA_NAV_TARGET_LON', '0')
    assert Member3NavigationService.target_configured()
    monkeypatch.delenv('LUNA_NAV_TARGET_LON')
    assert not Member3NavigationService.target_configured()


def test_require_real_rejects_every_mock_option(monkeypatch):
    for k in ('LUNA_SITE_URL', 'LUNA_VISIBILITY_URL', 'LUNA_NAVIGATION_URL'): monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv('LUNA_REQUIRE_REAL', '1')
    d = client.post('/mission/plan', json={**BASE, 'allow_mock_recommendation': True}).json()
    assert d['recommendation'] is None
    assert all('mock data disallowed' in o['violations'] for o in d['candidates'])
    assert d['limitations'] and 'landing-site terrain' in d['limitations'][0]


def test_limitations_name_only_the_mock_inputs():
    assert mock_limitations([]) == []
