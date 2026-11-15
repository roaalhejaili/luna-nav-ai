from datetime import datetime, timezone
import httpx
from fastapi.testclient import TestClient
from api.main import app
from schemas.models import Site, Visibility, Provenance
from tools.services import HttpLandingSiteService, HttpVisibilityService, HttpNavigationService
import orchestration.engine as engine

client=TestClient(app)
BASE={'dates_utc':['2030-01-01T00:00:00Z'],'duration_hours':48,
      'constraints':{'max_slope_deg':15,'min_sunlight_hours':0,'max_blackout_hours':72}}

def test_requirement_changes_selection_feasibility_and_replanning():
    terrain={'terrain':10,'sunlight':0,'communication':0,'navigation':0}
    sun={'terrain':0,'sunlight':10,'communication':0,'navigation':0}
    a=client.post('/mission/plan',json={**BASE,'priorities':terrain}).json()
    b=client.post('/mission/plan',json={**BASE,'priorities':sun}).json()
    assert a['recommendation']['site']['site_id']=='A'
    assert b['recommendation']['site']['site_id']=='B'
    assert [x['site']['site_id'] for x in a['ranked_alternatives']] != [x['site']['site_id'] for x in b['ranked_alternatives']]
    strict={**BASE,'constraints':{**BASE['constraints'],'max_slope_deg':7},'priorities':sun}
    r=client.post('/mission/replan',json={'previous':b,'requirements':strict})
    assert r.status_code==200
    assert r.json()['recommendation']['site']['site_id']=='A'
    assert len(r.json()['ranked_alternatives']) < len(b['ranked_alternatives'])

def test_invalid_and_missing_inputs():
    assert client.post('/mission/plan',json={'duration_hours':48}).status_code==422
    assert client.post('/mission/plan',json={**BASE,'duration_hours':-1}).status_code==422
    assert client.post('/mission/plan',json={**BASE,'priorities':{'terrain':-1}}).status_code==422

def test_service_failure_timeout_and_missing_science(monkeypatch):
    class Sites:
        async def candidates(self):
            raise httpx.TimeoutException('upstream timeout')
    class Vis: pass
    monkeypatch.setattr(engine,'services',lambda:(Sites(),Vis(),Vis()))
    response=TestClient(app,raise_server_exceptions=False).post('/mission/plan',json=BASE)
    assert response.status_code==502
    assert response.json()['error']['code']=='UPSTREAM_OR_PLANNING_ERROR'

def test_scientific_inconsistency_and_mixed_mock_warning(monkeypatch):
    verified=Provenance(status='VERIFIED',source='test',observed_at_utc=datetime.now(timezone.utc))
    mock=Provenance(status='MOCK',source='synthetic test',observed_at_utc=datetime.now(timezone.utc))
    class Sites:
        async def candidates(self): return [Site(site_id='X',name='X',latitude_deg=0,longitude_deg=0,elevation_m=0,slope_deg=1,provenance=verified)]
    class Vis:
        async def analyze(self,site_id,date_utc,duration_hours):
            return Visibility(site_id='WRONG',date_utc=date_utc,sunlight_hours=4,earth_visible_hours=4,max_blackout_hours=2,provenance=mock)
    monkeypatch.setattr(engine,'services',lambda:(Sites(),Vis(),None))
    body=client.post('/mission/plan',json=BASE).json()
    assert body['recommendation'] is None
    assert 'visibility response does not match' in body['candidates'][0]['violations'][0]
    assert any('MOCK' in x for x in body['warnings'])

def test_http_adapter_paths_and_schema(monkeypatch):
    seen=[]
    when=datetime(2030,1,1,tzinfo=timezone.utc)
    prov={'status':'VERIFIED','source':'integration fixture','observed_at_utc':when.isoformat()}
    def handler(req):
        seen.append((req.url.path,dict(req.url.params)))
        if req.url.path.endswith('/sites/candidates'):
            return httpx.Response(200,json=[{'site_id':'X','name':'X','latitude_deg':0,'longitude_deg':1,'elevation_m':0,'slope_deg':1,'provenance':prov}])
        if req.url.path.endswith('/visibility/analyze'):
            return httpx.Response(200,json={'site_id':'X','date_utc':when.isoformat(),'sunlight_hours':4,'earth_visible_hours':4,'max_blackout_hours':2,'provenance':prov})
        return httpx.Response(200,json={'site_id':'X','distance_m':100,'accessible':True,'provenance':prov})
    original=httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs))
    import asyncio
    async def run():
        assert (await HttpLandingSiteService('https://example.test').candidates())[0].site_id=='X'
        assert (await HttpVisibilityService('https://example.test').analyze('X',when,48)).site_id=='X'
        assert (await HttpNavigationService('https://example.test').route('X')).distance_m==100
    asyncio.run(run())
    assert [x[0] for x in seen]==['/sites/candidates','/visibility/analyze','/navigation/route']
    assert seen[1][1]['duration_hours']=='48'

def test_incomplete_upstream_response_and_invalid_science(monkeypatch):
    import asyncio
    from pydantic import ValidationError
    original=httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kwargs:original(
        transport=httpx.MockTransport(lambda req:httpx.Response(200,json={'site_id':'X'})),**kwargs))
    async def incomplete():
        await HttpVisibilityService('https://example.test').analyze('X',datetime(2030,1,1,tzinfo=timezone.utc),48)
    import pytest
    with pytest.raises(ValidationError): asyncio.run(incomplete())

    unverified=Provenance(status='UNVERIFIED',source='test',observed_at_utc=datetime.now(timezone.utc))
    class Sites:
        async def candidates(self): return [Site(site_id='X',name='X',latitude_deg=0,longitude_deg=0,elevation_m=0,slope_deg=1,provenance=unverified)]
    class Vis:
        async def analyze(self,site_id,date_utc,duration_hours):
            return Visibility(site_id=site_id,date_utc=date_utc,sunlight_hours=duration_hours+1,
                              earth_visible_hours=1,max_blackout_hours=2,provenance=unverified)
    monkeypatch.setattr(engine,'services',lambda:(Sites(),Vis(),None))
    body=client.post('/mission/plan',json=BASE).json()
    assert body['recommendation'] is None
    assert 'visibility duration exceeds mission duration' in body['candidates'][0]['violations']
    assert 'unverified scientific data' in body['candidates'][0]['violations']
