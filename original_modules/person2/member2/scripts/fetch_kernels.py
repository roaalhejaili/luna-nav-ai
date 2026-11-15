"""Download the SPICE kernels Member 02 needs from NASA NAIF (~44 MB total).

Run from the project folder:   python scripts/fetch_kernels.py
Kernels land in data/spice_kernels/. Safe to re-run: files with the right size are skipped.
Pure standard library. NAIF host was verified reachable from a normal browser on 2026-11-14
(file sizes below were read from the server with HEAD requests). It is NOT reachable from
some sandboxed shells; run this on your own machine.
"""
import sys
import urllib.request
from pathlib import Path

BASE = "https://naif.jpl.nasa.gov/pub/naif/generic_kernels/"
OUT = Path(__file__).resolve().parent.parent / "data" / "spice_kernels"

# (relative URL under BASE, expected size in MB as reported by the server, what it is)
KERNELS = [
    ("lsk/naif0012.tls", 0.01, "leap seconds (UTC <-> TDB time conversion)"),
    ("pck/pck00011.tpc", 0.13, "planetary constants (body radii, text PCK)"),
    ("pck/moon_pa_de440_200625.bpc", 12.27, "high-accuracy Moon orientation (DE440), binary PCK"),
    ("fk/satellites/moon_de440_250416.tf", 0.02, "Moon reference-frame definitions (MOON_ME, MOON_PA)"),
    ("spk/planets/de440s.bsp", 31.21, "planet/Moon/Sun positions, 1849-2150 (DE440s)"),
]


def fetch(rel: str, want_mb: float, what: str) -> Path:
    dest = OUT / Path(rel).name
    if dest.exists() and abs(dest.stat().st_size / 1048576 - want_mb) <= max(0.02, want_mb * 0.02):
        print(f"[skip] {dest.name} already present")
        return dest
    print(f"[get ] {rel}  ({want_mb} MB)  {what}")
    req = urllib.request.Request(BASE + rel, headers={"User-Agent": "luna-nav-ai/1.0"})
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    got = tmp.stat().st_size / 1048576
    if abs(got - want_mb) > max(0.02, want_mb * 0.02):
        tmp.unlink()
        sys.exit(f"size mismatch for {rel}: got {got:.2f} MB, expected about {want_mb} MB")
    tmp.replace(dest)
    return dest


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    files = [fetch(*k) for k in KERNELS]
    print("\nAll kernels present in", OUT)
    try:
        import spiceypy as sp
        for f in files:
            sp.furnsh(str(f))
        et = sp.str2et("2026-11-15T00:00:00")
        print("SpiceyPy smoke test OK. ET for 2026-11-15T00:00:00 UTC =", et)
        print("MOON_ME -> J2000 rotation available:", sp.pxform("MOON_ME", "J2000", et).shape == (3, 3))
    except ImportError:
        print("Install spiceypy to run the smoke test:  pip install spiceypy")
