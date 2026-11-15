"""Shared pytest fixtures.

* ``needs_kernels``: skipped (with a reason) when the SPICE kernels have not been downloaded.
* ``needs_lola``: skipped when data/lola/ldem_75s_240m.img is absent (scripts/fetch_lola.py).
* ``needs_network``: skipped when the live NASA/JPL Horizons API cannot be reached
  (one probe per test session). Set LUNA_OFFLINE=1 to skip them without probing.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from visibility_planner.kernels import kernels_available  # noqa: E402
from visibility_planner.sources import horizons_reachable  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
HAVE_KERNELS = kernels_available()
from visibility_planner.lola import PRODUCT as _LOLA, lola_dir  # noqa: E402
HAVE_LOLA = (lola_dir() / f"{_LOLA}.img").exists()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if not HAVE_KERNELS:
        skip = pytest.mark.skip(reason="SPICE kernels missing: run python scripts/fetch_kernels.py")
        for item in items:
            if "needs_kernels" in item.keywords:
                item.add_marker(skip)
    if not HAVE_LOLA:
        skip = pytest.mark.skip(reason="NASA LOLA DEM missing: run python scripts/fetch_lola.py")
        for item in items:
            if "needs_lola" in item.keywords:
                item.add_marker(skip)
    net_items = [i for i in items if "needs_network" in i.keywords]
    if net_items and (os.environ.get("LUNA_OFFLINE") == "1" or not horizons_reachable()):
        skip = pytest.mark.skip(reason="NASA/JPL Horizons API not reachable (or LUNA_OFFLINE=1)")
        for item in net_items:
            item.add_marker(skip)


@pytest.fixture
def horizons_reference() -> dict:
    path = FIXTURES / "horizons_reference.json"
    if not path.exists():
        pytest.skip("run python scripts/fetch_horizons_reference.py")
    return json.loads(path.read_text())


@pytest.fixture
def base_request() -> dict:
    """Offline (SPICE) request used by the kernel-based tests."""
    return {"site": {"site_id": "site_A", "lat_deg": -86.0, "lon_deg_east": 0.0, "alt_m": 0.0},
            "start_utc": "2026-11-15T00:00:00Z", "duration_days": 2, "step_minutes": 30,
            "engine": "spice"}


@pytest.fixture
def offline_horizons(monkeypatch):
    """Simulate no internet: every Horizons HTTP call raises URLError."""
    import urllib.error

    from visibility_planner import sources

    def boom(*_a, **_k):
        raise urllib.error.URLError("simulated offline")
    sources.clear_cache()
    sources.reset_failure_memory()
    monkeypatch.setattr(sources.urllib.request, "urlopen", boom)
    monkeypatch.setattr(sources.time, "sleep", lambda *_: None)
    yield
    sources.clear_cache()
    sources.reset_failure_memory()


@pytest.fixture(autouse=True)
def _fresh_horizons_failure_memory():
    """Each test starts without the 2-minute 'Horizons recently failed' memory."""
    from visibility_planner import sources
    sources.reset_failure_memory()
    yield
    sources.reset_failure_memory()
