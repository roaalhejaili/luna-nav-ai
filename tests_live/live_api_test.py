"""LUNA NAV AI v7 — live API test suite.

Runs against the real running stack (no TestClient, no mocks):
  Person 4 orchestrator  http://127.0.0.1:8000
  Person 1 site analyzer http://127.0.0.1:8001  (NASA LRO LOLA LDEM_75S_240M)
  Person 2 visibility    http://127.0.0.1:8002  (live NASA/JPL Horizons + LOLA horizon)
  Person 3 navigation    http://127.0.0.1:3003  (NASA LRO LOLA LDEM_75S_240M routes)

Independent checks (not using any team code):
  * Sun/Earth elevation re-queried directly from JPL Horizons and compared with Person 2.
  * Site elevations re-read directly from the LOLA DEM file and compared with Person 1.
  * Recommendation score recomputed by hand from the documented formula.

Usage: python -I live_api_test.py <path-to-ldem_75s_240m.img> <results.json>
"""
from __future__ import annotations
import json, math, sys, time, traceback
from datetime import datetime, timedelta, timezone
import httpx
import numpy as np

P4, P1, P2, P3 = 'http://127.0.0.1:8000', 'http://127.0.0.1:8001', 'http://127.0.0.1:8002', 'http://127.0.0.1:3003'
HORIZONS = 'https://ssd.jpl.nasa.gov/api/horizons.api'
DEM_PATH, OUT = sys.argv[1], sys.argv[2]
LONG = httpx.Client(timeout=900)
results: list[dict] = []
plan_cache: dict = {}

REAL_REQ = {
    'request': 'robotic science mission near lunar south pole',
    'mission_type': 'robotic',
    'dates_utc': ['2030-01-03T00:00:00Z', '2030-01-05T00:00:00Z'],
    'duration_hours': 48,
    'objectives': ['sunlight', 'Earth communication'],
    'priorities': {'terrain': 1, 'sunlight': 2, 'communication': 2, 'navigation': 0},
    'constraints': {'max_slope_deg': 15, 'min_sunlight_hours': 10, 'max_blackout_hours': 40},
    'require_navigation': False,
    'allow_mock_recommendation': False,
}


def test(name):
    def deco(fn):
        def run():
            t0 = time.perf_counter(); detail = {}
            try:
                detail = fn() or {}
                status = 'PASS'
            except AssertionError as e:
                status = 'FAIL'; detail = {'reason': str(e)}
            except Exception as e:
                status = 'ERROR'; detail = {'reason': f'{type(e).__name__}: {e}', 'trace': traceback.format_exc()[-800:]}
            ms = round((time.perf_counter() - t0) * 1000, 1)
            results.append({'test': name, 'ms': ms, **detail, 'status': status})
            print(f'[{status}] {name} ({ms} ms) {detail.get("reason", "")}', flush=True)
        run.__name__ = fn.__name__
        TESTS.append(run)
        return run
    return deco

TESTS: list = []


def real_plan():
    if 'plan' not in plan_cache:
        t0 = time.perf_counter()
        r = LONG.post(P4 + '/mission/plan', json=REAL_REQ)
        plan_cache['plan'] = (r, round(time.perf_counter() - t0, 1))
    return plan_cache['plan']


# ---------------------------------------------------------------- health
@test('L01 all four services report healthy')
def _():
    codes = {u: LONG.get(u).status_code for u in [P4 + '/health', P1 + '/api/v1/health', P2 + '/health', P3 + '/api/v1/health']}
    assert all(c == 200 for c in codes.values()), codes
    p2 = LONG.get(P2 + '/health').json()
    assert p2['kernels_available'] and p2['lola_dem_available'], p2
    return {'codes': codes}

@test('L02 Person 2 can reach live JPL Horizons')
def _():
    h = LONG.get(P2 + '/health', params={'check_upstream': 'true'}).json()
    assert h.get('horizons_reachable') is True and h['status'] == 'ok', h
    return {'horizons_reachable': True}

@test('L03 OpenAPI exposes the four public endpoints')
def _():
    paths = LONG.get(P4 + '/openapi.json').json()['paths']
    for p in ['/health', '/mission/plan', '/mission/replan', '/mission/compare']:
        assert p in paths, p

# ---------------------------------------------------------------- real-data end-to-end plan
@test('L04 POST /mission/plan end-to-end on NASA data returns 200')
def _():
    r, secs = real_plan()
    assert r.status_code == 200, (r.status_code, r.text[:500])
    d = r.json()
    assert d['candidates'], 'no candidates'
    return {'seconds': secs, 'candidates': len(d['candidates']),
            'feasible': sum(o['feasible'] for o in d['candidates']),
            'recommendation': None if not d['recommendation'] else
                f"{d['recommendation']['site']['site_id']} on {d['recommendation']['visibility']['date_utc'][:10]}"}

@test('L05 data provenance is NASA-sourced and honestly labelled (never MOCK, never VERIFIED)')
def _():
    d = real_plan()[0].json()
    for o in d['candidates']:
        s, v = o['site']['provenance'], o['visibility']['provenance']
        assert s['status'] == 'UNVERIFIED' and v['status'] == 'UNVERIFIED', (s['status'], v['status'])
        assert 'Member 1' in s['source'] and '(REAL)' in s['source'], s['source']
        assert 'Member 2' in v['source'] and '(REAL)' in v['source'], v['source']
    assert not any('MOCK' in w and 'demonstration' in w for w in d['warnings']), d['warnings']
    assert any('UNVERIFIED' in w for w in d['warnings']), 'missing UNVERIFIED warning'
    return {'site_source': d['candidates'][0]['site']['provenance']['source'],
            'visibility_source': d['candidates'][0]['visibility']['provenance']['source']}

@test('L06 candidate sites lie in the requested south-pole region with valid geometry')
def _():
    d = real_plan()[0].json()
    for o in d['candidates']:
        s = o['site']
        assert -90 <= s['latitude_deg'] <= -87.5, s
        assert 0 <= s['longitude_deg'] < 360 and 0 <= s['slope_deg'] <= 90, s
        assert s['coordinate_frame'].startswith('IAU_MOON_2015'), s['coordinate_frame']
    return {'sites': sorted({(o['site']['site_id'], round(o['site']['latitude_deg'], 3), round(o['site']['longitude_deg'], 3),
                              round(o['site']['elevation_m'], 1), round(o['site']['slope_deg'], 2)) for o in d['candidates']})}

@test('L07 visibility values are physically bounded by the mission duration')
def _():
    d = real_plan()[0].json(); dur = REAL_REQ['duration_hours']
    for o in d['candidates']:
        v = o['visibility']
        for k in ('sunlight_hours', 'earth_visible_hours', 'max_blackout_hours'):
            assert 0 <= v[k] <= dur + 1e-6, (k, v[k])
    return {}

@test('L08 every feasible option satisfies every hard constraint; every infeasible one names a violation')
def _():
    d = real_plan()[0].json(); c = REAL_REQ['constraints']
    for o in d['candidates']:
        v, s = o['visibility'], o['site']
        ok = s['slope_deg'] <= c['max_slope_deg'] and v['sunlight_hours'] >= c['min_sunlight_hours'] and v['max_blackout_hours'] <= c['max_blackout_hours']
        if o['feasible']:
            assert ok and not o['violations'], o
        else:
            assert o['violations'], o
            assert not ok, f"infeasible but meets all constraints: {o['violations']}"
    return {}

@test('L09 recommendation is the top-ranked feasible option')
def _():
    d = real_plan()[0].json()
    feas = [o for o in d['candidates'] if o['feasible']]
    if not feas:
        assert d['recommendation'] is None; return {'note': 'no feasible option -> null recommendation'}
    rec = d['recommendation']
    assert rec and rec['feasible'], rec
    assert rec == d['ranked_alternatives'][0]
    return {}

@test('L10 recommendation score matches hand-calculated weighted utility')
def _():
    d = real_plan()[0].json(); rec = d['recommendation']
    if not rec: return {'note': 'skipped: no recommendation'}
    p = REAL_REQ['priorities']; dur = REAL_REQ['duration_hours']
    terrain = max(0, 1 - rec['site']['slope_deg'] / 90)
    sun = min(1, rec['visibility']['sunlight_hours'] / dur)
    com = min(1, rec['visibility']['earth_visible_hours'] / dur)
    expected = (p['terrain'] * terrain + p['sunlight'] * sun + p['communication'] * com) / sum(p.values())
    assert abs(expected - rec['score']) < 1e-6, (expected, rec['score'])
    return {'score': rec['score'], 'hand_calc': round(expected, 6)}

@test('L11 deterministic mode: 0 LLM calls, no secrets in response')
def _():
    r = real_plan()[0]; d = r.json()
    assert d['metrics'].get('llm_calls') == 0, d['metrics']
    low = r.text.lower()
    for k in ('api_key', 'gemini_api', 'sk-', 'aiza'):
        assert k not in low, k
    return {'metrics': d['metrics']}

# ---------------------------------------------------------------- independent scientific cross-checks
def horizons_el(body: str, lat: float, lon_e: float, alt_km: float, t: datetime) -> float:
    lon = lon_e if lon_e <= 180 else lon_e - 360
    params = {'format': 'json', 'COMMAND': f"'{body}'", 'CENTER': "'coord@301'", 'COORD_TYPE': "'GEODETIC'",
              'SITE_COORD': f"'{lon:.6f},{lat:.6f},{alt_km:.6f}'", 'MAKE_EPHEM': "'YES'", 'EPHEM_TYPE': "'OBSERVER'",
              'START_TIME': f"'{t:%Y-%m-%d %H:%M}'", 'STOP_TIME': f"'{(t + timedelta(minutes=1)):%Y-%m-%d %H:%M}'",
              'STEP_SIZE': "'1 m'", 'QUANTITIES': "'4'", 'CSV_FORMAT': "'YES'", 'ANG_FORMAT': "'DEG'", 'EXTRA_PREC': "'YES'"}
    res = httpx.get(HORIZONS, params=params, timeout=60).json()['result']
    row = res.split('$$SOE')[1].split('$$EOE')[0].strip().splitlines()[0].split(',')
    vals = [x.strip() for x in row]
    return float(vals[-2]) if vals[-1] == '' else float(vals[-1])

@test('L12 Person 2 Sun/Earth elevation vs. direct JPL Horizons query (independent client)')
def _():
    d = real_plan()[0].json(); site = d['candidates'][0]['site']
    start = '2030-01-03T00:00:00Z'
    body = {'site': {'site_id': site['site_id'], 'lat_deg': site['latitude_deg'],
                     'lon_deg_east': site['longitude_deg'] if site['longitude_deg'] <= 180 else site['longitude_deg'] - 360},
            'start_utc': start, 'duration_days': 1, 'step_minutes': 360, 'include_time_series': True, 'engine': 'horizons'}
    r = LONG.post(P2 + '/api/v1/visibility/analyze', json=body)
    assert r.status_code == 200, r.text[:400]
    j = r.json(); alt_km = j.get('location', {}).get('alt_m', 0) / 1000
    rows = []; worst = 0
    for row in j['time_series'][:3]:
        t = datetime.fromisoformat(row['utc'].replace('Z', '+00:00'))
        sun = horizons_el('10', site['latitude_deg'], site['longitude_deg'], alt_km, t)
        earth = horizons_el('399', site['latitude_deg'], site['longitude_deg'], alt_km, t)
        ds, de = abs(sun - row['sun_el_deg']), abs(earth - row['earth_el_deg'])
        worst = max(worst, ds, de)
        rows.append({'utc': row['utc'], 'sun_p2': row['sun_el_deg'], 'sun_jpl': sun, 'earth_p2': row['earth_el_deg'], 'earth_jpl': earth})
    assert worst < 1e-3, f'max diff {worst} deg'
    return {'max_abs_diff_deg': worst, 'site_alt_m': alt_km * 1000, 'engine': j['data_source']['engine'], 'rows': rows}

@test('L13 Person 2 offline NAIF SPICE engine agrees with live Horizons engine')
def _():
    d = real_plan()[0].json(); site = d['candidates'][0]['site']
    base = {'site': {'site_id': site['site_id'], 'lat_deg': site['latitude_deg'],
                     'lon_deg_east': site['longitude_deg'] if site['longitude_deg'] <= 180 else site['longitude_deg'] - 360},
            'start_utc': '2030-01-03T00:00:00Z', 'duration_days': 2, 'step_minutes': 60, 'include_time_series': True}
    h = LONG.post(P2 + '/api/v1/visibility/analyze', json={**base, 'engine': 'horizons'}).json()
    s = LONG.post(P2 + '/api/v1/visibility/analyze', json={**base, 'engine': 'spice'}).json()
    assert h['data_source']['engine'] == 'horizons' and s['data_source']['engine'] == 'spice'
    diffs = [max(abs(a['sun_el_deg'] - b['sun_el_deg']), abs(a['earth_el_deg'] - b['earth_el_deg']))
             for a, b in zip(h['time_series'], s['time_series'])]
    assert len(diffs) >= 48 and max(diffs) < 0.01, max(diffs)
    return {'samples': len(diffs), 'max_abs_diff_deg': max(diffs)}

@test('L14 Person 1 site elevations vs. direct read of the NASA LOLA DEM file')
def _():
    d = real_plan()[0].json()
    n, R, scale, off = 3812, 1737400.0, 240.0, 1905.5
    dem = np.memmap(DEM_PATH, dtype='<i2', mode='r', shape=(n, n))
    out = []; worst = 0
    for s in {o['site']['site_id']: o['site'] for o in d['candidates']}.values():
        lat, lon = math.radians(s['latitude_deg']), math.radians(s['longitude_deg'])
        rho = 2 * R * math.tan(math.pi / 4 + lat / 2)          # PDS south polar stereographic
        x, y = rho * math.sin(lon), rho * math.cos(lon)
        row, col = off - y / scale, off + x / scale
        r0, c0 = int(round(row)), int(round(col))
        h = float(dem[r0, c0]) * 0.5
        diff = abs(h - s['elevation_m']); worst = max(worst, diff)
        out.append({'site': s['site_id'], 'p1_elev_m': round(s['elevation_m'], 1), 'dem_elev_m': h, 'diff_m': round(diff, 1)})
    assert worst < 50, out
    return {'max_abs_diff_m': worst, 'sites': out}

# ---------------------------------------------------------------- behaviour checks
@test('L15 POST /mission/replan keeps mission ID and applies new dates')
def _():
    prev = real_plan()[0].json()
    new = {**REAL_REQ, 'dates_utc': ['2030-01-04T00:00:00Z']}
    r = LONG.post(P4 + '/mission/replan', json={'previous': prev, 'requirements': new})
    assert r.status_code == 200, r.text[:400]
    d = r.json()
    assert d['mission_id'] == prev['mission_id']
    assert {o['visibility']['date_utc'][:10] for o in d['candidates']} == {'2030-01-04'}
    return {'mission_id': d['mission_id'], 'recommendation':
            None if not d['recommendation'] else d['recommendation']['site']['site_id']}

@test('L16 POST /mission/compare returns baseline and hybrid plans on NASA data')
def _():
    req = {**REAL_REQ, 'dates_utc': ['2030-01-03T00:00:00Z']}
    r = LONG.post(P4 + '/mission/compare', json={'requirements': req})
    assert r.status_code == 200, r.text[:400]
    d = r.json()
    b, h = d['baseline']['recommendation'], d['hybrid']['recommendation']
    for rec in (b, h):
        if rec: assert rec['feasible']
    return {'baseline': b and b['site']['site_id'], 'hybrid': h and h['site']['site_id'], 'metrics': d['metrics']}

@test('L17 impossible constraint (49 h sunlight in a 48 h mission) -> no recommendation, no crash')
def _():
    r = LONG.post(P4 + '/mission/plan', json={**REAL_REQ, 'dates_utc': ['2030-01-03T00:00:00Z'],
                                               'constraints': {**REAL_REQ['constraints'], 'min_sunlight_hours': 49}})
    assert r.status_code == 200, r.text[:300]
    d = r.json()
    assert d['recommendation'] is None and not any(o['feasible'] for o in d['candidates'])
    return {'candidates': len(d['candidates'])}

@test('L18 required navigation on NASA terrain: all 3 members REAL, zero MOCK anywhere')
def _():
    req = {**REAL_REQ, 'dates_utc': ['2030-01-03T00:00:00Z'], 'require_navigation': True,
           'priorities': {**REAL_REQ['priorities'], 'navigation': 1},
           'constraints': {**REAL_REQ['constraints'], 'max_route_m': 80000}, 'allow_mock_recommendation': False}
    r = LONG.post(P4 + '/mission/plan', json=req)
    assert r.status_code == 200, (r.status_code, r.text[:400])
    d = r.json()
    assert 'MOCK' not in json.dumps(d['limitations']), d['limitations']
    for o in d['candidates']:
        assert o['route'] is not None, 'route missing'
        provs = [o['site']['provenance'], o['visibility']['provenance'], o['route']['provenance']]
        assert all(p['status'] != 'MOCK' for p in provs), provs
        assert '(REAL)' in provs[0]['source'] and '(REAL)' in provs[1]['source']
        assert 'LOLA' in provs[2]['source'] and '(REAL)' in provs[2]['source'] or 'NO_ROUTE_FOUND' in provs[2]['source'], provs[2]['source']
        if o['feasible']:
            assert o['route']['accessible'] and o['route']['distance_m'] <= 80000
    assert d['recommendation'], d['warnings']
    return {'recommendation': d['recommendation']['site']['site_id'],
            'routes_km': sorted(round(o['route']['distance_m'] / 1000, 1) for o in d['candidates']),
            'route_source': d['recommendation']['route']['provenance']['source']}

@test('L24 every member health endpoint reports REAL NASA data')
def _():
    p1 = LONG.get(P1 + '/api/v1/health').json(); p3 = LONG.get(P3 + '/api/v1/health').json()
    p2 = LONG.get(P2 + '/health').json()
    assert p1['data_status'] == 'REAL' and p1['dem'] == 'ldem_75s_240m.img', p1
    assert p3['data_status'] == 'REAL' and 'LOLA' in p3['terrain_source']['name'], p3['terrain_source']
    assert p2['kernels_available'] and p2['lola_dem_available'] and p2['default_engine'] in ('auto', 'horizons'), p2
    return {'p1': p1['dem'], 'p3': p3['terrain_source']['name'], 'p2_engine': p2['default_engine']}

@test('L25 Person 3 and Person 1 read the same NASA DEM: route start elevation = site elevation')
def _():
    d = real_plan()[0].json(); out = []; worst = 0
    for s in list({o['site']['site_id']: o['site'] for o in d['candidates']}.values()):
        lon = s['longitude_deg'] if s['longitude_deg'] <= 180 else s['longitude_deg'] - 360
        r = LONG.post(P3 + '/api/v1/routes', json={'start': {'lat_deg': s['latitude_deg'], 'lon_deg': lon},
                      'target': {'lat_deg': -90, 'lon_deg': 0}, 'constraints': {'max_slope_deg': 20}})
        j = r.json(); e3 = (j.get('start') or {}).get('elevation_m')
        if e3 is None: continue
        diff = abs(e3 - s['elevation_m']); worst = max(worst, diff)
        out.append({'site': s['site_id'], 'p1_m': s['elevation_m'], 'p3_m': e3})
    assert out and worst < 30, out   # P3 interpolates bilinearly, P1 reads the pixel
    return {'max_abs_diff_m': round(worst, 1), 'sites': out}

BAD = {
    'naive timestamp': {**REAL_REQ, 'dates_utc': ['2030-01-03T00:00:00']},
    'empty dates': {**REAL_REQ, 'dates_utc': []},
    '31 dates': {**REAL_REQ, 'dates_utc': [f'2030-01-{(i % 28) + 1:02d}T00:00:00Z' for i in range(31)]},
    'zero duration': {**REAL_REQ, 'duration_hours': 0},
    'duration > 1 year': {**REAL_REQ, 'duration_hours': 9000},
    'negative priority': {**REAL_REQ, 'priorities': {'terrain': -1, 'sunlight': 1}},
    'all-zero priorities': {**REAL_REQ, 'priorities': {'terrain': 0, 'sunlight': 0, 'communication': 0, 'navigation': 0}},
    'unknown constraint': {**REAL_REQ, 'constraints': {'max_temperature_k': 300}},
    'negative constraint': {**REAL_REQ, 'constraints': {'max_slope_deg': -5}},
    'missing dates field': {k: v for k, v in REAL_REQ.items() if k != 'dates_utc'},
}

@test('L19 invalid requests are rejected with 422 (10 cases)')
def _():
    codes = {name: LONG.post(P4 + '/mission/plan', json=body).status_code for name, body in BAD.items()}
    bad = {k: v for k, v in codes.items() if v != 422}
    assert not bad, bad
    return {'codes': codes}

@test('L20 CORS allows the dashboard origin and blocks unknown origins')
def _():
    ok = LONG.options(P4 + '/mission/plan', headers={'Origin': 'http://localhost:5173', 'Access-Control-Request-Method': 'POST'})
    evil = LONG.options(P4 + '/mission/plan', headers={'Origin': 'http://evil.example', 'Access-Control-Request-Method': 'POST'})
    assert ok.headers.get('access-control-allow-origin') == 'http://localhost:5173', dict(ok.headers)
    assert 'access-control-allow-origin' not in evil.headers, dict(evil.headers)
    return {}

@test('L21 Person 3 route API serves NASA LOLA terrain (REAL, not the synthetic fixture)')
def _():
    body = {'start': {'lat_deg': -89.445, 'lon_deg': -137.314}, 'target': {'lat_deg': -90, 'lon_deg': 0},
            'constraints': {'max_slope_deg': 15}, 'algorithm': 'astar', 'strategies': ['shortest']}
    r = LONG.post(P3 + '/api/v1/routes', json=body)
    assert r.status_code == 200, r.text[:300]
    j = r.json()
    assert j['data_status'] == 'REAL' and 'LOLA' in j['terrain_source']['name'], (j['data_status'], j['terrain_source'])
    return {'distance_m': j['alternatives'][0]['distance_m'], 'terrain': j['terrain_source']['name']}

@test('L22 Person 1 rejects bad region (lat out of range) with 4xx')
def _():
    r = LONG.post(P1 + '/api/v1/landing-sites/candidates', json={'mission_id': 'x', 'target_region': {'body': 'Moon',
        'coordinate_reference': 'MEAN_EARTH_POLAR_AXIS', 'projection': 'EQUIRECTANGULAR',
        'bounds': {'min_latitude_deg': -95, 'max_latitude_deg': -80, 'min_longitude_deg': 0, 'max_longitude_deg': 10}}})
    assert 400 <= r.status_code < 500, (r.status_code, r.text[:300])
    return {'status': r.status_code}

@test('L23 Person 2 rejects a naive (non-UTC) timestamp')
def _():
    r = LONG.post(P2 + '/api/v1/visibility/analyze', json={'site': {'site_id': 'x', 'lat_deg': -89.5, 'lon_deg_east': 0},
                                                            'start_utc': '2030-01-03T00:00:00', 'duration_days': 1})
    assert 400 <= r.status_code < 500, (r.status_code, r.text[:300])
    return {'status': r.status_code}


if __name__ == '__main__':
    for t in TESTS: t()
    summary = {k: sum(r['status'] == k for r in results) for k in ('PASS', 'FAIL', 'ERROR')}
    print('SUMMARY', summary)
    json.dump({'run_utc': datetime.now(timezone.utc).isoformat(), 'request': REAL_REQ, 'summary': summary, 'results': results},
              open(OUT, 'w', encoding='utf-8'), indent=2, default=str)
