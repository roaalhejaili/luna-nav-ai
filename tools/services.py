from __future__ import annotations
import os
from datetime import datetime, timezone
from typing import Protocol
import httpx
from schemas.models import Site, Visibility, Route, Provenance

def mock_source():
    return Provenance(status='MOCK', source='LUNA Person 4 deterministic fixture', observed_at_utc=datetime.now(timezone.utc), uncertainty='Synthetic demonstration values; not scientific measurements')

class LandingSiteService(Protocol):
    async def candidates(self) -> list[Site]: ...

class VisibilityService(Protocol):
    async def analyze(self, site_id: str, date_utc: datetime, duration_hours: float) -> Visibility: ...

class NavigationService(Protocol):
    async def route(self, site_id: str) -> Route: ...

class MockLandingSiteService:
    async def candidates(self):
        return [Site(site_id=i, name=n, latitude_deg=lat, longitude_deg=lon, elevation_m=e, slope_deg=s, provenance=mock_source()) for i,n,lat,lon,e,s in [
            ('A','South Polar Ridge',-89.1,45,-1200,6), ('B','Crater Rim',-88.7,90,-1800,12), ('C','Highland Plain',-87.5,120,500,19)]]

class MockVisibilityService:
    async def analyze(self, site_id, date_utc, duration_hours):
        # Deterministic fixture keyed by site and day; all values explicitly MOCK.
        base = {'A': (0.75, 0.70, 12), 'B': (0.90, 0.45, 30), 'C': (0.55, 0.80, 8)}[site_id]
        shift = (date_utc.toordinal() % 3 - 1) * 0.05
        return Visibility(site_id=site_id, date_utc=date_utc, sunlight_hours=duration_hours*max(0,min(1,base[0]+shift)), earth_visible_hours=duration_hours*base[1], max_blackout_hours=base[2], provenance=mock_source())

class MockNavigationService:
    FIXTURE = {'A':(2500,True),'B':(5300,True),'C':(9000,False)}
    async def route(self, site_id):
        d,a = self.FIXTURE[site_id]
        return Route(site_id=site_id,distance_m=d,accessible=a,provenance=mock_source())

class HttpAdapter:
    def __init__(self, url: str):
        self.url=url.rstrip('/')
        self.timeout=float(os.getenv('LUNA_HTTP_TIMEOUT_SECONDS','10'))
    async def get(self, path, params=None):
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r=await client.get(self.url+path,params=params)
            r.raise_for_status()
            return r.json()

class HttpLandingSiteService(HttpAdapter):
    async def candidates(self):
        return [Site.model_validate(x) for x in await self.get('/sites/candidates')]

class HttpVisibilityService(HttpAdapter):
    async def analyze(self, site_id, date_utc, duration_hours):
        return Visibility.model_validate(await self.get('/visibility/analyze', {'site_id':site_id,'date_utc':date_utc.isoformat(),'duration_hours':duration_hours}))

class HttpNavigationService(HttpAdapter):
    async def route(self, site_id):
        return Route.model_validate(await self.get('/navigation/route', {'site_id':site_id}))

def services():
    a=os.getenv('LUNA_SITE_URL'); b=os.getenv('LUNA_VISIBILITY_URL'); c=os.getenv('LUNA_NAVIGATION_URL')
    from tools.member_adapters import Member1LandingSiteService, Member2VisibilityService, Member3NavigationService
    return (Member1LandingSiteService(a) if a else MockLandingSiteService(),
            Member2VisibilityService(b) if b else MockVisibilityService(),
            Member3NavigationService(c) if c else MockNavigationService())
