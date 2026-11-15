"""SPICE kernel loading for the visibility planner.

SPICE is NASA/NAIF's toolkit for space geometry. "Kernels" are its data files: leap seconds,
planetary constants, body orientation and ephemerides (positions of Sun, Earth and Moon over time).

This module is the ONLY place with global state: the set of kernels already furnished
(loaded) into the CSPICE kernel pool. CSPICE is not thread-safe, so every SPICE call made
by this package runs while holding ``SPICE_LOCK``.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path

import spiceypy as sp
from spiceypy.utils.exceptions import SpiceyError

#: Environment variable that overrides the kernel directory.
KERNEL_DIR_ENV = "LUNA_SPICE_KERNEL_DIR"

#: Default kernel directory: <project>/data/spice_kernels (no absolute paths hardcoded).
DEFAULT_KERNEL_DIR = Path(__file__).resolve().parent.parent / "data" / "spice_kernels"

#: Preferred Moon body-fixed frame, and the DE440 fallback if the frame kernel lacks it.
PREFERRED_FRAME = "MOON_ME"
FALLBACK_FRAME = "MOON_ME_DE440_ME421"

#: Re-entrant lock serialising all CSPICE access (CSPICE keeps global state).
SPICE_LOCK = threading.RLock()


@dataclass(frozen=True)
class KernelSpec:
    """One SPICE kernel file the planner depends on."""

    name: str
    url: str
    role: str


_BASE = "https://naif.jpl.nasa.gov/pub/naif/generic_kernels/"
KERNEL_SET: tuple[KernelSpec, ...] = (
    KernelSpec("naif0012.tls", _BASE + "lsk/naif0012.tls",
               "leap seconds: converts UTC to ephemeris time (TDB)"),
    KernelSpec("pck00011.tpc", _BASE + "pck/pck00011.tpc",
               "planetary constants: Sun and Earth radii for apparent disk size"),
    KernelSpec("moon_pa_de440_200625.bpc", _BASE + "pck/moon_pa_de440_200625.bpc",
               "high-accuracy lunar orientation (DE440 principal axes)"),
    KernelSpec("moon_de440_250416.tf", _BASE + "fk/satellites/moon_de440_250416.tf",
               "lunar frame definitions (MOON_ME mean-Earth/polar-axis, MOON_PA)"),
    KernelSpec("de440s.bsp", _BASE + "spk/planets/de440s.bsp",
               "DE440s ephemeris: Sun, Earth, Moon positions 1849-2150"),
)


class KernelError(RuntimeError):
    """Raised when kernels are missing or cannot be loaded. Message says how to fix it."""


_loaded: dict[str, object] = {"dir": None, "frame": None}


def resolve_kernel_dir(kernel_dir: str | Path | None = None) -> Path:
    """Return the kernel directory: explicit argument > $LUNA_SPICE_KERNEL_DIR > project default."""
    if kernel_dir is not None:
        return Path(kernel_dir)
    env = os.environ.get(KERNEL_DIR_ENV)
    return Path(env) if env else DEFAULT_KERNEL_DIR


def missing_kernels(kernel_dir: str | Path | None = None) -> list[str]:
    """Names of required kernels absent from ``kernel_dir`` (empty list = all present)."""
    d = resolve_kernel_dir(kernel_dir)
    return [k.name for k in KERNEL_SET if not (d / k.name).is_file()]


def kernels_available(kernel_dir: str | Path | None = None) -> bool:
    """True when every required kernel file exists (does not load them)."""
    return not missing_kernels(kernel_dir)


def load_kernels(kernel_dir: str | Path | None = None) -> str:
    """Load all required kernels once (idempotent) and return the Moon body-fixed frame name.

    Raises:
        KernelError: directory or a kernel file is missing, or no usable lunar frame exists.
    """
    d = resolve_kernel_dir(kernel_dir).resolve()
    with SPICE_LOCK:
        if _loaded["dir"] == d and _loaded["frame"]:
            return str(_loaded["frame"])
        if not d.is_dir():
            raise KernelError(
                f"SPICE kernel directory not found: {d}. Run `python scripts/fetch_kernels.py` "
                f"or set {KERNEL_DIR_ENV}.")
        missing = missing_kernels(d)
        if missing:
            raise KernelError(
                f"Missing SPICE kernels in {d}: {', '.join(missing)}. "
                "Run `python scripts/fetch_kernels.py`.")
        if _loaded["dir"] is not None:
            sp.kclear()  # switching directories: start from a clean kernel pool
        for k in KERNEL_SET:
            sp.furnsh(str(d / k.name))
        frame = _pick_frame()
        _loaded.update(dir=d, frame=frame)
        return frame


def ensure_loaded() -> str:
    """Return the active lunar frame, loading kernels from the default location only if none are loaded."""
    with SPICE_LOCK:
        if _loaded["frame"]:
            return str(_loaded["frame"])
        return load_kernels()


def _pick_frame() -> str:
    """Verify the lunar frame resolves via pxform; fall back to the DE440 frame name explicitly."""
    et = sp.str2et("2026-11-15T00:00:00")
    for name in (PREFERRED_FRAME, FALLBACK_FRAME):
        try:
            sp.pxform(name, "J2000", et)
            return name
        except SpiceyError:
            continue
    raise KernelError(f"Neither {PREFERRED_FRAME} nor {FALLBACK_FRAME} is defined by the loaded kernels.")


def loaded_frame() -> str | None:
    """Frame chosen by the last successful load_kernels call, or None."""
    return _loaded["frame"]  # type: ignore[return-value]


def unload_kernels() -> None:
    """Clear the kernel pool (used by tests)."""
    with SPICE_LOCK:
        sp.kclear()
        _loaded.update(dir=None, frame=None)


def kernel_manifest() -> list[dict[str, str]]:
    """``[{"name", "role", "url"}]`` for every kernel, for embedding in outputs."""
    return [{"name": k.name, "role": k.role, "url": k.url} for k in KERNEL_SET]
