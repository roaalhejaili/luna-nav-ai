from schemas.models import Requirements, Site, Visibility, Route

def landing_agent(site: Site, req: Requirements) -> list[str]:
    return ['slope exceeds maximum'] if site.slope_deg > req.constraints.get('max_slope_deg', 90) else []

def solar_communication_agent(v: Visibility, req: Requirements) -> list[str]:
    problems=[]
    if v.sunlight_hours < req.constraints.get('min_sunlight_hours', 0): problems.append('insufficient sunlight')
    if v.max_blackout_hours > req.constraints.get('max_blackout_hours', float('inf')): problems.append('blackout exceeds maximum')
    if v.sunlight_hours > req.duration_hours or v.earth_visible_hours > req.duration_hours: problems.append('visibility duration exceeds mission duration')
    return problems

def navigation_agent(route: Route | None, req: Requirements) -> list[str]:
    if not req.require_navigation: return []
    if route is None: return ['route missing']
    problems=[]
    if not route.accessible: problems.append('route inaccessible')
    if route.distance_m > req.constraints.get('max_route_m', float('inf')): problems.append('route exceeds maximum distance')
    return problems
