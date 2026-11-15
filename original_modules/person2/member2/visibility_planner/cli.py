"""Command-line interface.

Examples:
  python -m visibility_planner --lat -86 --lon 0 --start 2026-11-15T00:00:00Z --days 7 --out r.json
  python -m visibility_planner --lat -86 --lon 0 --start 2026-11-15T00:00:00Z --days 7 --horizon-id ridge
  python -m visibility_planner --request examples/scenario_1.json --out examples/output/scenario_1.json
Data: live NASA/JPL Horizons API by default (no download); --engine spice uses local kernels.
Exit codes: 0 ok, 2 invalid input, 3 kernels unavailable, 4 Horizons unavailable/error,
5 LOLA terrain unavailable.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .horizon import HorizonProfile
from .kernels import KernelError
from .lola import TerrainError
from .planner import analyze_site
from .sources import UpstreamError

EXIT_OK, EXIT_BAD_INPUT, EXIT_NO_KERNELS, EXIT_UPSTREAM, EXIT_NO_TERRAIN = 0, 2, 3, 4, 5


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m visibility_planner",
                                description="Sun/Earth visibility windows for a lunar site (NASA JPL Horizons / SPICE).")
    p.add_argument("--request", type=Path, help="JSON request file (VisibilityRequest). "
                   "Other flags override its fields.")
    p.add_argument("--site-id", default=None)
    p.add_argument("--lat", type=float, help="latitude deg, south negative")
    p.add_argument("--lon", type=float, help="east longitude deg")
    p.add_argument("--alt-m", type=float, default=None, help="altitude above sphere, meters")
    p.add_argument("--start", help="start UTC, ISO-8601 with Z, e.g. 2026-11-15T00:00:00Z")
    p.add_argument("--end", help="end UTC (alternative to --days)")
    p.add_argument("--days", type=float, help="duration in days")
    p.add_argument("--step-min", type=float, default=None, help="sampling step, minutes (default 10)")
    p.add_argument("--definition", choices=["center", "upper_limb"], default=None)
    p.add_argument("--horizon", type=Path, help="horizon profile JSON file")
    p.add_argument("--horizon-id", choices=["lola", "flat", "ridge", "crater_rim"],
                   help="lola = REAL horizon from NASA LOLA (south of 75 S); others = synthetic MOCK")
    p.add_argument("--observer-height-m", type=float, default=None,
                   help="observer height above terrain for --horizon-id lola (default 2 m)")
    p.add_argument("--no-time-series", action="store_true", help="omit time_series from output")
    p.add_argument("--engine", choices=["horizons", "spice", "auto"], default=None,
                   help="data source: auto (default: live NASA Horizons API, offline SPICE fallback), "
                        "horizons (live only), spice (local kernels only)")
    p.add_argument("--kernel-dir", type=Path, help="SPICE kernel directory (engine spice/auto)")
    p.add_argument("--out", type=Path, help="write full JSON here (default: print to stdout)")
    return p


def _request_from_args(a: argparse.Namespace) -> dict[str, Any]:
    req: dict[str, Any] = json.loads(a.request.read_text(encoding="utf-8")) if a.request else {}
    site = dict(req.get("site", {}))
    for key, val in (("site_id", a.site_id), ("lat_deg", a.lat), ("lon_deg_east", a.lon),
                     ("alt_m", a.alt_m)):
        if val is not None:
            site[key] = val
    req["site"] = site
    if a.start:
        req["start_utc"] = a.start
    if a.end:
        req["end_utc"], req["duration_days"] = a.end, None
    if a.days is not None:
        req["duration_days"], req["end_utc"] = a.days, None
    if a.step_min is not None:
        req["step_minutes"] = a.step_min
    if a.definition:
        req["visibility_definition"] = a.definition
    if a.horizon:
        req["horizon_profile"] = HorizonProfile.from_file(a.horizon).model_dump()
        req.pop("horizon_profile_id", None)
    if a.horizon_id:
        req["horizon_profile_id"] = a.horizon_id
        req.pop("horizon_profile", None)
    if a.engine:
        req["engine"] = a.engine
    if a.observer_height_m is not None:
        req["observer_height_m"] = a.observer_height_m
    if a.no_time_series:
        req["include_time_series"] = False
    return {k: v for k, v in req.items() if v is not None}


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    try:
        result = analyze_site(_request_from_args(a), kernel_dir=a.kernel_dir)
    except ValidationError as e:
        msgs = "; ".join(f"{'.'.join(map(str, x['loc'])) or 'request'}: {x['msg']}" for x in e.errors())
        print(f"error: invalid input: {msgs}", file=sys.stderr)
        return EXIT_BAD_INPUT
    except (KeyError, ValueError, OSError) as e:
        print(f"error: invalid input: {e}", file=sys.stderr)
        return EXIT_BAD_INPUT
    except TerrainError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_BAD_INPUT if e.code == "OUT_OF_COVERAGE" else EXIT_NO_TERRAIN
    except KernelError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_NO_KERNELS
    except UpstreamError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_UPSTREAM
    payload = result.model_dump(mode="json")
    text = json.dumps(payload, indent=1)
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(text, encoding="utf-8")
        print(json.dumps({"site_id": payload["site_id"], "data_status": payload["data_status"],
                          "engine": (payload.get("data_source") or {}).get("engine"),
                          "horizon": payload["horizon"], "summary": payload["summary"],
                          "n_windows": len(payload["windows"]), "out": str(a.out)}, indent=1))
    else:
        print(text)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
