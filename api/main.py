import os, traceback
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from schemas.models import Requirements, ReplanRequest, CompareRequest, CompareResponse
from orchestration.engine import plan

app=FastAPI(title='LUNA NAV Person 4 Mission Optimizer',version='1.0.0')
ORIGINS=[x.strip() for x in os.getenv('LUNA_CORS_ORIGINS','http://localhost:5173,http://127.0.0.1:5173').split(',') if x.strip()]
app.add_middleware(CORSMiddleware,allow_origins=ORIGINS,
                   allow_methods=['GET','POST'],allow_headers=['Content-Type'])

@app.exception_handler(Exception)
async def failure(request, exc):
    # This handler runs outside the CORS middleware, so add the CORS header here; without it the
    # browser hides the real error and the interface reports the planner as unreachable.
    origin=request.headers.get('origin'); headers={'Access-Control-Allow-Origin':origin,'Vary':'Origin'} if origin in ORIGINS else {}
    if isinstance(exc, HTTPException): return JSONResponse(status_code=exc.status_code,content={'error':{'code':'HTTP_ERROR','message':str(exc.detail)}},headers=headers)
    traceback.print_exception(exc)
    return JSONResponse(status_code=502,content={'error':{'code':'UPSTREAM_OR_PLANNING_ERROR','message':f'{type(exc).__name__}: {exc}'}},headers=headers)

@app.get('/health')
async def health(): return {'status':'ok','mode':'standalone'}

@app.post('/mission/plan')
async def create_plan(req: Requirements): return await plan(req)

@app.post('/mission/replan')
async def replan(req: ReplanRequest): return await plan(req.requirements,req.previous)

@app.post('/mission/compare',response_model=CompareResponse)
async def compare(req: CompareRequest):
    baseline=await plan(req.requirements,baseline=True)
    hybrid=await plan(req.requirements)
    return CompareResponse(baseline=baseline,hybrid=hybrid,metrics={'baseline':baseline.metrics,'hybrid':hybrid.metrics})
