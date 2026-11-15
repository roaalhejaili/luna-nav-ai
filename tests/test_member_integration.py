import asyncio, json, sys
from datetime import datetime, timezone
from pathlib import Path
import httpx
from fastapi.testclient import TestClient
from schemas.models import Requirements, Site, Provenance
from tools.member_adapters import Member1LandingSiteService, Member2VisibilityService

ROOT=Path(__file__).resolve().parents[1]

def test_member1_actual_api_through_adapter(monkeypatch):
    sys.path.insert(0,str(ROOT/'original_modules'/'person1'))
    from landing_site_analyzer.app import app
    member=TestClient(app)
    original=httpx.AsyncClient
    def handler(req):
        response=member.post(req.url.path,json=json.loads(req.content))
        return httpx.Response(response.status_code,json=response.json())
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs))
    monkeypatch.setenv('LUNA_MEMBER1_DATA_MODE','mock')
    req=Requirements(dates_utc=[datetime(2030,1,1,tzinfo=timezone.utc)],duration_hours=48)
    sites=asyncio.run(Member1LandingSiteService('https://member1.test').candidates(req,'mission-test'))
    assert sites and all(s.provenance.status=='MOCK' for s in sites)
    assert all(0<=s.longitude_deg<360 and s.latitude_deg<=-75 for s in sites)

def test_member2_contract_fixture_through_adapter(monkeypatch):
    data=json.loads((ROOT/'original_modules'/'person2'/'member2'/'examples'/'mock_visibility_response.json').read_text())
    date=datetime(2030,1,1,tzinfo=timezone.utc); duration=48
    site=Site(site_id='X',name='X',latitude_deg=-86,longitude_deg=0,elevation_m=0,slope_deg=2,
        provenance=Provenance(status='MOCK',source='test',observed_at_utc=date))
    data.update(site_id='X',start_utc='2030-01-01T00:00:00Z',end_utc='2030-01-03T00:00:00Z',generated_utc='2030-01-01T00:00:00Z')
    data['location'].update(lat_deg=-86,lon_deg_east=0)
    original=httpx.AsyncClient; requests=[]
    def handler(req):
        requests.append(req)
        return httpx.Response(200,json=data)
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs))
    result=asyncio.run(Member2VisibilityService('https://member2.test').analyze(site,date,duration))
    assert result.provenance.status=='MOCK'
    assert result.sunlight_hours==data['summary']['sun_visible_fraction_terrain']*duration
    assert result.max_blackout_hours==data['summary']['longest_no_contact_hours_terrain']
    assert requests[0].url.path=='/api/v1/visibility/analyze'
    sent=json.loads(requests[0].content)
    assert sent['site']['site_id']=='X' and sent['duration_days']==2

def test_end_to_end_member1_and_member2_contract_fixture(monkeypatch):
    sys.path.insert(0,str(ROOT/'original_modules'/'person1'))
    from landing_site_analyzer.app import app as member1_app
    from api.main import app as optimizer_app
    member1=TestClient(member1_app)
    fixture=json.loads((ROOT/'original_modules'/'person2'/'member2'/'examples'/'mock_visibility_response.json').read_text())
    original=httpx.AsyncClient
    def handler(req):
        body=json.loads(req.content)
        if req.url.path.startswith('/api/v1/landing-sites/'):
            response=member1.post(req.url.path,json=body)
            return httpx.Response(response.status_code,json=response.json())
        assert req.url.path=='/api/v1/visibility/analyze'
        data=json.loads(json.dumps(fixture)); site=body['site']
        data['site_id']=site['site_id']; data['location'].update(lat_deg=site['lat_deg'],lon_deg_east=site['lon_deg_east'])
        data['start_utc']=body['start_utc']; data['end_utc']='2030-01-03T00:00:00Z'; data['generated_utc']='2030-01-01T00:00:00Z'
        return httpx.Response(200,json=data)
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs))
    monkeypatch.setenv('LUNA_SITE_URL','https://member1.test')
    monkeypatch.setenv('LUNA_VISIBILITY_URL','https://member2.test')
    monkeypatch.setenv('LUNA_MEMBER1_DATA_MODE','mock')
    monkeypatch.setenv('LUNA_CANDIDATE_COUNT','3')
    response=TestClient(optimizer_app).post('/mission/plan',json={'dates_utc':['2030-01-01T00:00:00Z'],'duration_hours':48})
    assert response.status_code==200,response.text
    plan=response.json()
    assert len(plan['candidates'])==3
    assert all(x['site']['provenance']['status']=='MOCK' and x['visibility']['provenance']['status']=='MOCK' for x in plan['candidates'])
    assert all(x['site']['site_id']==x['visibility']['site_id'] for x in plan['candidates'])
