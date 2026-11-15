from __future__ import annotations
import asyncio, os, re, time, uuid
from datetime import datetime, timezone
from typing import TypedDict, Literal
from pydantic import BaseModel
from langgraph.graph import StateGraph, START, END
from schemas.models import Requirements, Option, PlanResponse
from agents.specialists import landing_agent, solar_communication_agent, navigation_agent
from optimization.ranking import score, optimize
from tools.services import services, MockNavigationService
from tools.member_adapters import Member1LandingSiteService, Member2VisibilityService, Member3NavigationService
from orchestration import gemini

class MissionState(TypedDict, total=False):
    mission_id: str
    requirements: Requirements
    previous: PlanResponse | None
    baseline: bool
    site_service: object
    visibility_service: object
    navigation_service: object
    sites: list
    measurements: list
    options: list[Option]
    ranked: list[Option]
    warnings: list[str]
    calls: int
    llm_calls: int
    ai_summary: str | None
    llm_provider: str
    notes: list[str]

class Interpretation(BaseModel):
    mission_type: Literal['science','exploration','cargo','robotic','crewed']
    explanation_focus: Literal['terrain','sunlight','communication']

def parse_request(req: Requirements) -> Requirements:
    if req.request and req.mission_type=='science':
        match=re.search(r'\b(science|exploration|cargo|robotic|crewed)\b',req.request,re.I)
        if match: req=req.model_copy(update={'mission_type':match.group(1).lower()})
    return req

async def supervisor(state: MissionState) -> dict:
    req=parse_request(state['requirements']); calls=0; provider='none'
    if gemini.enabled() and req.request:
        calls=1; provider='gemini'  # one bounded attempt, deterministic fallback
        try:
            parsed=await gemini.interpret(req.request)
            explicit=re.search(r'\b(science|exploration|cargo|robotic|crewed)\b',req.request,re.I)
            if parsed and state['requirements'].mission_type=='science' and not explicit: req=req.model_copy(update={'mission_type':parsed['mission_type']})
        except Exception: pass
    elif os.getenv('OPENAI_API_KEY') and req.request:
        provider='openai'
        try:
            from openai import AsyncOpenAI
            client=AsyncOpenAI(api_key=os.environ['OPENAI_API_KEY'],timeout=5,max_retries=0)
            result=await client.beta.chat.completions.parse(model=os.getenv('LUNA_LLM_MODEL','gpt-4o-mini'),
                messages=[{'role':'system','content':'Classify mission type and explanation focus only. Never output measurements or requirements.'},
                          {'role':'user','content':req.request}],response_format=Interpretation)
            calls=1; parsed=result.choices[0].message.parsed
            if parsed and state['requirements'].mission_type=='science': req=req.model_copy(update={'mission_type':parsed.mission_type})
        except Exception: calls=1  # one bounded attempt, deterministic fallback
    return {'requirements':req,'llm_calls':calls,'calls':0,'llm_provider':provider,'ai_summary':None}

async def site_analysis(state: MissionState) -> dict:
    service=state['site_service']
    sites=await service.candidates(state['requirements'],state['mission_id']) if isinstance(service,Member1LandingSiteService) else await service.candidates()
    return {'sites':sites,'calls':state['calls']+1}

async def visibility_analysis(state: MissionState) -> dict:
    req=state['requirements']; previous=state.get('previous'); calls=state['calls']
    prior={(o.site.site_id,o.visibility.date_utc):o for o in previous.candidates} if previous else {}
    service=state['visibility_service']
    # Site/date analyses are independent; run a few at once (Person 2's Horizons calls are network-bound).
    # Order of the result rows is unchanged. LUNA_VISIBILITY_CONCURRENCY=1 restores strictly sequential calls.
    gate=asyncio.Semaphore(max(1,int(os.getenv('LUNA_VISIBILITY_CONCURRENCY','4'))))
    async def one(site,date):
        old=prior.get((site.site_id,date))
        same=bool(old and old.site.model_dump(exclude={'provenance'})==site.model_dump(exclude={'provenance'}))
        reusable=bool(same and previous.requirements.duration_hours==req.duration_hours
            and old.site.provenance.status=='VERIFIED' and old.visibility.provenance.status=='VERIFIED'
            and site.provenance.status=='VERIFIED')
        if reusable: return old.visibility,0
        async with gate:
            visibility=await service.analyze(site,date,req.duration_hours) if isinstance(service,Member2VisibilityService) else await service.analyze(site.site_id,date,req.duration_hours)
        return visibility,1
    pairs=[(site,date) for site in state['sites'] for date in req.dates_utc]
    results=await asyncio.gather(*(one(site,date) for site,date in pairs))
    rows=[(site,date,visibility,None) for (site,date),(visibility,_) in zip(pairs,results)]
    calls+=sum(n for _,n in results)
    return {'measurements':rows,'calls':calls}

async def navigation_analysis(state: MissionState) -> dict:
    service=state['navigation_service']
    if isinstance(service,MockNavigationService) and any(site.site_id not in MockNavigationService.FIXTURE for site,*_ in state['measurements']):
        # Route service (Person 3) not configured: the demo fixture only knows sites A/B/C. Do not invent
        # routes for real sites; plan without the traverse requirement and say so.
        req=state['requirements'].model_copy(update={'require_navigation':False})
        return {'requirements':req,'notes':state.get('notes',[])+['Route service (Person 3) not running: traverse access was not scored for these sites. '
                'Start it (pnpm install, then pnpm start in original_modules/person3/moon_navigation) to include routes in the ranking.']}
    rows=[]; calls=state['calls']
    for site,date,visibility,route in state['measurements']:
        if route is None:
            service=state['navigation_service']
            route=await service.route(site,state['requirements'].constraints.get('max_slope_deg',15)) if isinstance(service,Member3NavigationService) else await service.route(site.site_id)
            calls+=1
        rows.append((site,date,visibility,route))
    return {'measurements':rows,'calls':calls}

def validation_agent(state: MissionState) -> dict:
    req=state['requirements']; options=[]; mock=False; unverified=False
    # Opt-in for accuracy testing with real supplier data (default off = original behaviour).
    allow_unverified=os.getenv('LUNA_ALLOW_UNVERIFIED_RECOMMENDATION','0')=='1'
    for site,date,v,route in state['measurements']:
        violations=landing_agent(site,req)+solar_communication_agent(v,req)+navigation_agent(route,req)
        if v.site_id!=site.site_id or v.date_utc!=date: violations.append('visibility response does not match requested site/date')
        if route and route.site_id!=site.site_id: violations.append('route response does not match requested site')
        provenance=[site.provenance,v.provenance]+([route.provenance] if route else [])
        if any(p.observed_at_utc.tzinfo is None or p.observed_at_utc.utcoffset() is None for p in provenance): violations.append('provenance timestamp lacks timezone')
        statuses=[p.status for p in provenance]; mock |= 'MOCK' in statuses; unverified |= 'UNVERIFIED' in statuses
        if 'UNVERIFIED' in statuses and not allow_unverified: violations.append('unverified scientific data')
        if 'MOCK' in statuses and (not req.allow_mock_recommendation or os.getenv('LUNA_REQUIRE_REAL')=='1'):
            violations.append('mock data disallowed')
        options.append(Option(site=site,visibility=v,route=route,feasible=not violations,violations=violations,explanation=''))
    warnings=list(state.get('notes',[]))+(['MOCK data: demonstration only; no flight or scientific recommendation'] if mock else [])
    if unverified and allow_unverified:
        warnings.append('UNVERIFIED supplier data accepted for testing (LUNA_ALLOW_UNVERIFIED_RECOMMENDATION=1): '
                        'NASA-derived values not independently reviewed; provisional, not a flight recommendation')
    return {'options':options,'warnings':warnings}

def optimization_agent(state: MissionState) -> dict:
    req=state['requirements']; options=state['options']
    for option in options:
        if option.feasible: option.score=score(option,req)
    feasible=[x for x in options if x.feasible]
    ranked=sorted(feasible,key=lambda x:(-x.score,x.site.site_id,x.visibility.date_utc)) if state['baseline'] else optimize(options,req)
    return {'options':options,'ranked':ranked}

async def explanation_agent(state: MissionState) -> dict:
    chosen=state['ranked'][0] if state['ranked'] else None
    for option in state['options']:
        provenance=[option.site.provenance,option.visibility.provenance]+([option.route.provenance] if option.route else [])
        status='MOCK' if any(p.status=='MOCK' for p in provenance) else 'UNVERIFIED' if any(p.status=='UNVERIFIED' for p in provenance) else 'VERIFIED'
        if option.feasible:
            option.explanation=(f'{status} evidence; slope {option.site.slope_deg} deg, sunlight {option.visibility.sunlight_hours:.2f} h, '
                                f'Earth visibility {option.visibility.earth_visible_hours:.2f} h; weighted score {option.score:.6f}.')
            if option is chosen: option.explanation+=' Selected from feasible Pareto alternatives.' if not state['baseline'] else ' Highest baseline weighted score.'
        else: option.explanation=f'{status} evidence; rejected: '+', '.join(option.violations)
    summary=None; calls=state.get('llm_calls',0)
    if chosen and gemini.enabled() and os.getenv('LUNA_GEMINI_EXPLAIN','1')=='1':
        prov=[chosen.site.provenance,chosen.visibility.provenance]+([chosen.route.provenance] if chosen.route else [])
        evidence={'data_status':'MOCK' if any(p.status=='MOCK' for p in prov) else 'UNVERIFIED' if any(p.status=='UNVERIFIED' for p in prov) else 'VERIFIED',
                  'latitude_deg':round(chosen.site.latitude_deg,2),'longitude_deg':round(chosen.site.longitude_deg,2),
                  'slope_deg':round(chosen.site.slope_deg,1),'blackout_hours':round(chosen.visibility.max_blackout_hours,1),
                  'sunlight_hours':round(chosen.visibility.sunlight_hours,1),'earth_visible_hours':round(chosen.visibility.earth_visible_hours,1),
                  'window_hours':state['requirements'].duration_hours,'score':round(chosen.score,3),
                  'feasible_options':len(state['ranked']),'options_checked':len(state['options'])}
        calls+=1
        try: summary=await gemini.summarize(evidence,os.getenv('LUNA_GEMINI_LANG','en'))
        except Exception: summary=None
    return {'options':state['options'],'ranked':state['ranked'],'ai_summary':summary,'llm_calls':calls}

def mock_limitations(options: list[Option]) -> list[str]:
    """Name exactly which inputs were MOCK instead of calling the whole run 'mock mode'."""
    parts=[]
    if any(o.site.provenance.status=='MOCK' for o in options): parts.append('landing-site terrain')
    if any(o.visibility.provenance.status=='MOCK' for o in options): parts.append('Sun/Earth visibility')
    if any(o.route and o.route.provenance.status=='MOCK' for o in options): parts.append('navigation routes')
    return [f"MOCK (synthetic, not NASA) inputs used for: {', '.join(parts)}"] if parts else []

def graph():
    g=StateGraph(MissionState)
    for name,fn in [('supervisor',supervisor),('site_analysis',site_analysis),('visibility_analysis',visibility_analysis),
                    ('navigation_analysis',navigation_analysis),('validation',validation_agent),
                    ('optimization',optimization_agent),('explanation',explanation_agent)]: g.add_node(name,fn)
    g.add_edge(START,'supervisor'); g.add_edge('supervisor','site_analysis'); g.add_edge('site_analysis','visibility_analysis')
    g.add_conditional_edges('visibility_analysis',lambda s:'navigation_analysis' if s['requirements'].require_navigation else 'validation',
                            {'navigation_analysis':'navigation_analysis','validation':'validation'})
    g.add_edge('navigation_analysis','validation'); g.add_edge('validation','optimization'); g.add_edge('optimization','explanation'); g.add_edge('explanation',END)
    return g.compile()

async def plan(req: Requirements, previous: PlanResponse | None=None, baseline=False) -> PlanResponse:
    start=time.perf_counter(); a,b,c=services(); mission_id=previous.mission_id if previous else str(uuid.uuid4())
    if req.require_navigation and isinstance(c,Member3NavigationService) and not c.target_configured():
        # Fail before minutes of visibility work, with a client-actionable message (was a 502 at the end).
        from fastapi import HTTPException
        raise HTTPException(status_code=422,detail='Navigation was required but no traverse target is configured on the server: '
                            'set LUNA_NAV_TARGET_LAT and LUNA_NAV_TARGET_LON (scripts/start_real_nasa.ps1 does this), or untick navigation.')
    state=await graph().ainvoke({'requirements':req,'previous':previous,'baseline':baseline,'mission_id':mission_id,
                                 'site_service':a,'visibility_service':b,'navigation_service':c},config={'recursion_limit':12})
    ranked=state['ranked']; recommendation=ranked[0] if ranked else None
    warnings=state['warnings']+(['No feasible candidate'] if not recommendation else [])
    return PlanResponse(mission_id=mission_id,requirements=state['requirements'],
        candidates=state['options'],ranked_alternatives=ranked,recommendation=recommendation,warnings=warnings,
        ai_summary=state.get('ai_summary'),llm_provider=state.get('llm_provider','none'),
        limitations=mock_limitations(state['options']),
        generated_at_utc=datetime.now(timezone.utc),
        metrics={'runtime_ms':round((time.perf_counter()-start)*1000,3),'llm_calls':state['llm_calls'],'tool_calls':state['calls'],
                 'constraint_satisfaction':int(bool(recommendation)),'valid_recommendation_rate':int(bool(recommendation)),
                 'unsupported_claim_rate':0,'replanning_success':int(previous is not None and bool(recommendation))})
