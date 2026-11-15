from scipy.optimize import milp, Bounds, LinearConstraint
import numpy as np
from schemas.models import Option, Requirements

def utilities(option: Option, req: Requirements) -> dict[str,float]:
    s=option.site; v=option.visibility; r=option.route
    u={'terrain':max(0,1-s.slope_deg/90), 'sunlight':min(1,v.sunlight_hours/req.duration_hours),
       'communication':min(1,v.earth_visible_hours/req.duration_hours),
       'navigation': max(0,1-r.distance_m/100000) if r and r.accessible else 0}
    return u

def score(option: Option, req: Requirements) -> float:
    u=utilities(option,req); w=req.priorities
    return round(sum(w.get(k,0)*u[k] for k in u)/sum(w.values()),6)

def dominates(a: Option,b: Option,req: Requirements) -> bool:
    ua,ub=utilities(a,req),utilities(b,req)
    keys=[k for k,v in req.priorities.items() if v>0]
    return all(ua[k]>=ub[k]-1e-10 for k in keys) and any(ua[k]>ub[k]+1e-10 for k in keys)

def optimize(options: list[Option], req: Requirements) -> list[Option]:
    """Pareto layers with binary candidate selection MILP within each layer."""
    remaining=[x for x in options if x.feasible]; ranked=[]
    while remaining:
        front=[x for x in remaining if not any(dominates(y,x,req) for y in remaining if y is not x)]
        while front:
            values=np.array([score(x,req) for x in front])
            result=milp(c=-values,integrality=np.ones(len(front)),
                        bounds=Bounds(np.zeros(len(front)),np.ones(len(front))),
                        constraints=LinearConstraint(np.ones((1,len(front))),[1],[1]),
                        options={'time_limit':5})
            if not result.success: raise RuntimeError('Candidate optimization failed')
            index=next(i for i,v in enumerate(result.x) if v>0.5)
            chosen=front.pop(index); ranked.append(chosen); remaining.remove(chosen)
    return ranked
