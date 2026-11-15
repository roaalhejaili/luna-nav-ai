"""Download NASA LRO LOLA south-polar elevation grid LDEM_75S_240M (~29 MB) into data/lola/.

    python scripts/fetch_lola.py

Optional: the planner downloads it automatically the first time a LOLA horizon is requested
(disable with LUNA_LOLA_AUTO_DOWNLOAD=0). Source: NASA PDS Geosciences Node,
https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/data/lola_gdr/polar/img/
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from visibility_planner.lola import LolaDEM, download  # noqa: E402

if __name__ == "__main__":
    img = download(progress=True)
    dem = LolaDEM.open()
    print("OK:", img, f"{dem.n}x{dem.n} px, {dem.scale_m:.0f} m/px, coverage to {dem.max_lat_deg} deg")
    print("height at south pole (m above 1737.4 km):", float(dem.height_m(-90.0, 0.0)))
