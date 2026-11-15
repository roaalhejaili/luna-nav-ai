import inspect
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from api.main import app
import orchestration.engine as engine
from optimization.ranking import score, dominates, optimize
from schemas.models import Requirements, Site, Visibility, Option, Provenance, FRAME

client=TestClient(app)
BASE={'dates_utc':['2030-01-01T00:00:00Z','2030-01-02T00:00:00Z'],'duration_hours':48}

def post(body):
    r=client.post('/mission/plan',json=body)
    assert r.status_code==200,r.text
    return r.json()

def test_six_mission_scenarios_and_explanations():
    solar=post({**BASE,'priorities':{'terrain':0,'sunlight':10,'communication':0,'navigation':0}})
    comm=post({**BASE,'priorities':{'terrain':0,'sunlight':0,'communication':10,'navigation':0}})
    terrain=post({**BASE,'constraints':{'max_slope_deg':7}})
    nav=post({**BASE,'require_navigation':True,'constraints':{'max_route_m':3000}})
    impossible=post({**BASE,'constraints':{'max_slope_deg':1}})
    assert solar['recommendation']['site']['site_id']=='B'
    assert comm['recommendation']['site']['site_id']=='A'
    assert terrain['recommendation']['site']['site_id']=='A'
    assert nav['recommendation']['site']['site_id']=='A'
    assert all(x['route'] for x in nav['candidates'])
    assert impossible['recommendation'] is None and len(impossible['ranked_alternatives'])==0
    assert 'No feasible candidate' in impossible['warnings']
    assert 'MOCK evidence' in solar['recommendation']['explanation']
    assert str(solar['recommendation']['site']['slope_deg']) in solar['recommendation']['explanation']
    replanned=client.post('/mission/replan',json={'previous':solar,'requirements':{
        **BASE,'dates_utc':['2030-01-03T00:00:00Z'],'constraints':{'max_slope_deg':7}}})
    assert replanned.status_code==200
    assert replanned.json()['mission_id']==solar['mission_id']
    assert replanned.json()['recommendation']['visibility']['date_utc']=='2030-01-03T00:00:00Z'

def test_real_graph_nodes_execute_and_navigation_conditional(monkeypatch):
    names=['supervisor','site_analysis','visibility_analysis','navigation_analysis','validation_agent','optimization_agent','explanation_agent']
    seen=[]
    for name in names:
        original=getattr(engine,name)
        if inspect.iscoroutinefunction(original):  # explanation_agent is async too
            async def wrapper(state,original=original,name=name):
                seen.append(name); return await original(state)
        else:
            def wrapper(state,original=original,name=name):
                seen.append(name); return original(state)
        monkeypatch.setattr(engine,name,wrapper)
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    ordinary=post(BASE)
    assert seen==['supervisor','site_analysis','visibility_analysis','validation_agent','optimization_agent','explanation_agent']
    assert ordinary['metrics']['llm_calls']==0
    seen.clear(); post({**BASE,'require_navigation':True})
    assert 'navigation_analysis' in seen and len(seen)==7

def test_independently_calculated_optimization_and_baseline():
    req=Requirements(dates_utc=[datetime(2030,1,1,tzinfo=timezone.utc)],duration_hours=10,
        priorities={'terrain':1,'sunlight':1,'communication':0,'navigation':0})
    p=Provenance(status='MOCK',source='test',observed_at_utc=datetime.now(timezone.utc))
    def option(name,slope,sun):
        site=Site(site_id=name,name=name,latitude_deg=0,longitude_deg=0,elevation_m=0,slope_deg=slope,provenance=p)
        vis=Visibility(site_id=name,date_utc=req.dates_utc[0],sunlight_hours=sun,earth_visible_hours=0,max_blackout_hours=0,provenance=p)
        return Option(site=site,visibility=vis,feasible=True,violations=[],explanation='')
    a,b,c=option('A',0,5),option('B',45,10),option('C',90,0)
    assert score(a,req)==0.75 and score(b,req)==0.75 and score(c,req)==0
    assert not dominates(a,b,req) and not dominates(b,a,req)
    assert dominates(a,c,req)
    assert {x.site.site_id for x in optimize([a,b,c],req)[:2]}=={'A','B'}
    assert optimize([a,b,c],req)[-1].site.site_id=='C'
    comparison=client.post('/mission/compare',json={'requirements':BASE})
    assert comparison.status_code==200
    assert comparison.json()['baseline']['ranked_alternatives']

def test_scientific_schema_and_missing_payload():
    with pytest.raises(ValidationError): Provenance(status='VERIFIED',source='x',observed_at_utc='2030-01-01T00:00:00')
    p=Provenance(status='MOCK',source='test',observed_at_utc=datetime.now(timezone.utc))
    with pytest.raises(ValidationError): Site(site_id='X',name='X',latitude_deg=0,longitude_deg=0,elevation_m=0,slope_deg=1,coordinate_frame='wrong',provenance=p)
    with pytest.raises(ValidationError): Visibility(site_id='X',date_utc='2030-01-01T00:00:00',sunlight_hours=1,earth_visible_hours=1,max_blackout_hours=1,provenance=p)
    r=client.post('/mission/plan',json={'duration_hours':48})
    assert r.status_code==422
    r=client.post('/mission/plan',json={**BASE,'dates_utc':'wrong type'})
    assert r.status_code==422

def test_empty_candidates_offline_and_concurrent(monkeypatch):
    class Empty:
        async def candidates(self): return []
    class Forbidden:
        async def analyze(self,*args): raise AssertionError('unexpected call')
        async def route(self,*args): raise AssertionError('unexpected call')
    monkeypatch.setattr(engine,'services',lambda:(Empty(),Forbidden(),Forbidden()))
    empty=post(BASE)
    assert empty['recommendation'] is None and empty['candidates']==[]
    monkeypatch.undo()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:client.get('/health').status_code,range(2)))
    assert results==[200,200]

def test_openapi_and_no_secret_echo(monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    schema=client.get('/openapi.json')
    assert schema.status_code==200
    assert all(path in schema.json()['paths'] for path in ['/health','/mission/plan','/mission/replan','/mission/compare'])
    body=post(BASE)
    assert 'OPENAI_API_KEY' not in str(body)
    assert all(x['site']['provenance']['status']=='MOCK' and x['visibility']['provenance']['status']=='MOCK' for x in body['candidates'])
