"""Export actual OpenAPI and mock UI states without external service calls."""
import json, os
from pathlib import Path
from fastapi.testclient import TestClient
from api.main import app

for key in ('LUNA_SITE_URL','LUNA_VISIBILITY_URL','LUNA_NAVIGATION_URL'):
    os.environ.pop(key,None)
root=Path(__file__).resolve().parents[1]
output=root/'FRONTEND_DATA_EXAMPLES'; output.mkdir(exist_ok=True)
client=TestClient(app)
request=json.loads((root/'examples'/'demo_request.json').read_text())
planned=client.post('/mission/plan',json=request)
assert planned.status_code==200
plan=planned.json()
no_result=client.post('/mission/plan',json={**request,'constraints':{'max_slope_deg':1}})
assert no_result.status_code==200 and no_result.json()['recommendation'] is None
replanned=client.post('/mission/replan',json={'previous':plan,'requirements':{**request,'priorities':{'terrain':0,'sunlight':5,'communication':0,'navigation':0}}})
compared=client.post('/mission/compare',json={'requirements':request})
assert replanned.status_code==compared.status_code==200
artifacts={'plan_mock.json':plan,'no_feasible_mock.json':no_result.json(),
           'replan_mock.json':replanned.json(),'compare_mock.json':compared.json(),
           'validation_error.json':client.post('/mission/plan',json={'duration_hours':48}).json()}
for name,data in artifacts.items(): (output/name).write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
(root/'openapi.json').write_text(json.dumps(app.openapi(),indent=2)+'\n',encoding='utf-8')
print('Generated',len(artifacts),'examples and openapi.json')
