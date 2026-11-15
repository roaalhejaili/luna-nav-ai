"""Download NASA LRO LOLA elevation grids from the NASA PDS Geosciences Node.

    .venv\\Scripts\\python.exe scripts\\get_nasa_lola.py                     # LDEM_75S_240M (29 MB) for Person 2 + frontend
    .venv\\Scripts\\python.exe scripts\\get_nasa_lola.py --product ldem_16   # LDEM_16 (32 MB) cylindrical, for Person 1
    .venv\\Scripts\\python.exe scripts\\get_nasa_lola.py --product ldsm_75s_240m   # NASA official slope map, for the accuracy check

Standard library only. Parallel HTTP Range requests (the PDS server is slow per connection),
resumable: run it again after a network drop and it continues where it stopped.
"""
import os, sys, time, threading, urllib.request
from pathlib import Path

BASE = "https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/data/lola_gdr/"
ROOT = Path(__file__).resolve().parent.parent
PRODUCTS = {   # sizes from the PDS labels / directory listing
    "ldem_75s_240m": (BASE + "polar/img/ldem_75s_240m.img", 29_062_688, ROOT / "original_modules" / "person2" / "member2" / "data" / "lola"),
    "ldem_16": (BASE + "cylindrical/img/ldem_16.img", 33_177_600, ROOT / "original_modules" / "person1" / "data"),
    # NASA's official LOLA slope map (slopes from laser-shot plane fits, 30-120 m baseline); size read from its label
    "ldsm_75s_240m": (BASE + "polar/img/ldsm_75s_240m.img", None, ROOT / "original_modules" / "person2" / "member2" / "data" / "lola"),
}
PRODUCT = sys.argv[sys.argv.index("--product") + 1] if "--product" in sys.argv else "ldem_75s_240m"
URL, SIZE, _dir = PRODUCTS[PRODUCT]
LBL_URL = URL[:-4] + ".lbl"
WORKERS = 8
DEST = _dir / f"{PRODUCT}.img"

try:                        # the PDS certificate chain needs the OS store on some machines
    import truststore; truststore.inject_into_ssl()
except ImportError:
    pass

def get(url, start=None, end=None, timeout=60):
    h = {"User-Agent": "luna-nav-ai/frontend-terrain"}
    if start is not None: h["Range"] = f"bytes={start}-{end}"
    return urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout)

def fetch_part(part, start, end, errors):
    want = end - start + 1
    for _ in range(200):
        have = part.stat().st_size if part.exists() else 0
        if have >= want: return
        try:
            with get(URL, start + have, end) as r, open(part, "ab") as f:
                if r.status != 206: raise RuntimeError("server ignored the Range header")
                while chunk := r.read(128 * 1024): f.write(chunk)
        except Exception as e:  # network drop: wait and resume
            errors.append(str(e)); time.sleep(3)
    if not part.exists() or part.stat().st_size < want:
        raise RuntimeError(f"{part.name} incomplete")

def main():
    DEST.parent.mkdir(parents=True, exist_ok=True)
    lbl = DEST.with_suffix(".lbl")
    global SIZE
    if not lbl.exists():
        with get(LBL_URL) as r: lbl.write_bytes(r.read())
    if SIZE is None:
        import re
        t = lbl.read_text(encoding="latin-1")
        SIZE = int(re.search(r"^\s*RECORD_BYTES\s*=\s*(\d+)", t, re.M).group(1)) * int(re.search(r"^\s*FILE_RECORDS\s*=\s*(\d+)", t, re.M).group(1))
    if DEST.exists() and DEST.stat().st_size == SIZE:
        print(f"Already complete: {DEST}"); return
    bounds = [SIZE * k // WORKERS for k in range(WORKERS + 1)]
    parts = [(DEST.with_name(f"{DEST.name}.part{k}"), bounds[k], bounds[k + 1] - 1) for k in range(WORKERS)]
    errors = []; threads = [threading.Thread(target=fetch_part, args=(p, a, b, errors), daemon=True) for p, a, b in parts]
    for t in threads: t.start()
    t0 = time.time()
    while any(t.is_alive() for t in threads):
        got = sum(p.stat().st_size for p, _, _ in parts if p.exists())
        rate = got / max(1, time.time() - t0) / 1024
        print(f"\rNASA LOLA {PRODUCT.upper()}: {got / 1048576:5.1f} / {SIZE / 1048576:.1f} MB  ({rate:.0f} KB/s, {len(errors)} retries)   ", end="", flush=True)
        time.sleep(1)
    print()
    got = sum(p.stat().st_size for p, _, _ in parts if p.exists())
    if got != SIZE:
        sys.exit(f"Download incomplete ({got} of {SIZE} bytes). Run the same command again to resume.")
    with open(DEST, "wb") as out:
        for p, _, _ in parts: out.write(p.read_bytes())
    for p, _, _ in parts: p.unlink()
    print(f"Done: {DEST} ({SIZE:,} bytes)")

if __name__ == "__main__":
    main()
