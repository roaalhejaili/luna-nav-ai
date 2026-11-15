from fastapi.testclient import TestClient
from api.main import app

client=TestClient(app)
REQ={'request':'robotic polar science','dates_utc':['2030-01-01T00:00:00Z','2030-01-02T00:00:00Z'],
     'duration_hours':48,'constraints':{'max_slope_deg':15,'min_sunlight_hours':20,'max_blackout_hours':40}}

def test_health(): assert client.get('/health').json()['status']=='ok'

def test_plan_and_replan():
    p=client.post('/mission/plan',json=REQ)
    assert p.status_code==200,p.text
    body=p.json(); assert len(body['candidates'])==6
    assert body['recommendation']['site']['provenance']['status']=='MOCK'
    assert all(x['feasible'] for x in body['ranked_alternatives'])
    changed={**REQ,'priorities':{'terrain':1,'sunlight':3,'communication':1,'navigation':0}}
    r=client.post('/mission/replan',json={'previous':body,'requirements':changed})
    assert r.status_code==200,r.text
    assert r.json()['mission_id']==body['mission_id']

def test_compare_and_validation():
    assert client.post('/mission/compare',json={'requirements':REQ}).status_code==200
    bad={**REQ,'dates_utc':['2030-01-01T00:00:00']}
    assert client.post('/mission/plan',json=bad).status_code==422

def test_mock_rejection():
    p=client.post('/mission/plan',json={**REQ,'allow_mock_recommendation':False})
    assert p.json()['recommendation'] is None

def test_mock_provenance_and_navigation():
    p=client.post('/mission/plan',json={**REQ,'require_navigation':True,
        'constraints':{**REQ['constraints'],'max_route_m':6000}})
    assert p.status_code==200,p.text
    body=p.json()
    assert any('MOCK data' in warning for warning in body['warnings'])
    assert all(x['site']['provenance']['status']=='MOCK' and
               x['visibility']['provenance']['status']=='MOCK' and
               x['route']['provenance']['status']=='MOCK' for x in body['candidates'])
    assert all(x['site']['coordinate_frame'].startswith('IAU_MOON_2015') for x in body['candidates'])
    assert body['recommendation']['route']['accessible']
