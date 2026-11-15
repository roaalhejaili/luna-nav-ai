import asyncio, json
from datetime import datetime, timezone
from pathlib import Path
import httpx
import pytest
from schemas.models import Site, Provenance
from tools.member_adapters import Member3NavigationService

FIXTURE=Path(__file__).resolve().parents[1]/'original_modules'/'person3_contract'/'fixtures'/'route_response.example.json'

def site():
    return Site(site_id='X',name='X',latitude_deg=-88.811008,longitude_deg=303.690068,elevation_m=1821.4,slope_deg=2,
        provenance=Provenance(status='MOCK',source='fixture',observed_at_utc=datetime.now(timezone.utc)))

def test_member3_route_contract_fixture(monkeypatch):
    fixture=json.loads(FIXTURE.read_text()); original=httpx.AsyncClient; seen=[]
    def handler(req):
        seen.append(req)
        return httpx.Response(200,json=fixture)
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    monkeypatch.setenv('LUNA_NAV_TARGET_LAT','-88.833164'); monkeypatch.setenv('LUNA_NAV_TARGET_LON','132.70939')
    route=asyncio.run(Member3NavigationService('https://member3.test').route(site(),15))
    assert route.distance_m==74555.4 and route.provenance.status=='MOCK'
    assert seen[0].url.path=='/api/v1/routes'
    sent=json.loads(seen[0].content)
    assert sent['start']['lon_deg']==pytest.approx(-56.309932)
    assert sent['constraints']['max_slope_deg']==15

def test_member3_missing_target_and_bad_frame(monkeypatch):
    monkeypatch.delenv('LUNA_NAV_TARGET_LAT',raising=False)
    monkeypatch.delenv('LUNA_NAV_TARGET_LON',raising=False)
    with pytest.raises(ValueError,match='LUNA_NAV_TARGET'):
        asyncio.run(Member3NavigationService('https://member3.test').route(site(),15))
    monkeypatch.setenv('LUNA_NAV_TARGET_LAT','-88.833164'); monkeypatch.setenv('LUNA_NAV_TARGET_LON','132.70939')
    fixture=json.loads(FIXTURE.read_text()); fixture['frame']='wrong'
    original=httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(lambda req:httpx.Response(200,json=fixture)),**kw))
    with pytest.raises(ValueError,match='frame mismatch'):
        asyncio.run(Member3NavigationService('https://member3.test').route(site(),15))

def test_member3_no_route_marks_site_inaccessible_instead_of_failing(monkeypatch):
    original=httpx.AsyncClient
    body={'error':{'code':'NO_ROUTE_FOUND','message':'No route satisfies max_slope_deg=15 between the given points.'}}
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(lambda r:httpx.Response(422,json=body)),**kw))
    monkeypatch.setenv('LUNA_NAV_TARGET_LAT','-90'); monkeypatch.setenv('LUNA_NAV_TARGET_LON','0')
    route=asyncio.run(Member3NavigationService('https://member3.test').route(site(),15))
    assert route.accessible is False and 'NO_ROUTE_FOUND' in route.provenance.source

def test_member3_other_422_still_raises(monkeypatch):
    original=httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(lambda r:httpx.Response(422,json={'error':{'code':'VALIDATION_ERROR'}})),**kw))
    monkeypatch.setenv('LUNA_NAV_TARGET_LAT','-90'); monkeypatch.setenv('LUNA_NAV_TARGET_LON','0')
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(Member3NavigationService('https://member3.test').route(site(),15))
