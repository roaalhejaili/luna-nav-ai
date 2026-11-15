"""Call a running Person 3 server through Person 4's adapter."""
import asyncio, os
from datetime import datetime, timezone
from schemas.models import Site, Provenance
from tools.member_adapters import Member3NavigationService

os.environ['LUNA_NAV_TARGET_LAT']='-88.833164'
os.environ['LUNA_NAV_TARGET_LON']='132.70939'
site=Site(site_id='live-test',name='Fixture start',latitude_deg=-88.811008,longitude_deg=303.690068,
          elevation_m=1821.4,slope_deg=2,
          provenance=Provenance(status='MOCK',source='Person 3 published fixture',observed_at_utc=datetime.now(timezone.utc)))
route=asyncio.run(Member3NavigationService(os.getenv('LUNA_NAVIGATION_URL','http://127.0.0.1:3003')).route(site,15))
assert route.distance_m>0 and route.provenance.status=='MOCK'
print({'distance_m':route.distance_m,'data_status':route.provenance.status,'source':route.provenance.source})
