"""Run a complete MOCK mission through the four public endpoints."""
import json
from pathlib import Path
from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)
request = json.loads((Path(__file__).parent / 'demo_request.json').read_text())
health = client.get('/health')
planned = client.post('/mission/plan', json=request)
assert health.status_code == planned.status_code == 200
plan = planned.json()
assert len(plan['candidates']) == 6 and plan['recommendation']
assert all(x['site']['provenance']['status'] == 'MOCK' and
           x['visibility']['provenance']['status'] == 'MOCK' for x in plan['candidates'])
assert any('MOCK' in warning for warning in plan['warnings'])

changed = {**request, 'priorities': {'terrain': 1, 'sunlight': 3, 'communication': 1, 'navigation': 0}}
replanned = client.post('/mission/replan', json={'previous': plan, 'requirements': changed})
compared = client.post('/mission/compare', json={'requirements': request})
assert replanned.status_code == compared.status_code == 200
assert replanned.json()['mission_id'] == plan['mission_id']

print(json.dumps({
    'health': health.json(),
    'plan_status': planned.status_code,
    'candidates': len(plan['candidates']),
    'feasible': len(plan['ranked_alternatives']),
    'recommended_site': plan['recommendation']['site']['site_id'],
    'recommended_date_utc': plan['recommendation']['visibility']['date_utc'],
    'recommendation_data_status': plan['recommendation']['site']['provenance']['status'],
    'replan_status': replanned.status_code,
    'replan_mission_id_preserved': replanned.json()['mission_id'] == plan['mission_id'],
    'compare_status': compared.status_code,
    'compare_metrics': compared.json()['metrics'],
}, indent=2))
