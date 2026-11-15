"""NASA LRO LOLA south-polar elevation grid (PDS GDR) reader.

LOLA = Lunar Orbiter Laser Altimeter on NASA's Lunar Reconnaissance Orbiter. It measured the
Moon's shape with a laser; the LOLA team gridded billions of shots into elevation maps (DEMs).

Product: LDEM_75S_240M (75 S to the pole, 240 m/pixel), PDS Geosciences Node, NASA.
  * 3812 x 3812 little-endian int16; height_m = DN * 0.5, relative to the 1737.4 km sphere
    (the same sphere this module uses), frame "MEAN EARTH/POLAR AXIS OF DE421" (= MOON_ME family).
  * Polar stereographic, centre -90 deg. Pixel <-> lat/lon follows the forward equations of
    the PDS catalog DSMAP_POLAR.CAT and its text ("In the south, Longitude 0 extends straight
    up from the center, and Longitude 90 East extends to the right"):
        X = (I - N/2 - 0.5) * scale,   Y = -(J - N/2 - 0.5) * scale     (I sample, J line, 1-based)
        lon = atan2(X, Y),  lat = -90 + 2 atan(R / (2 * 1737400)),  R = hypot(X, Y)
    (The inverse equations printed in that catalog carry a sign slip that would mirror the
    map east-west; orientation is verified against known craters in tests/test_lola.py.)
The file (29 MB) is downloaded once on first use and cached in data/lola/.
"""
from __future__ import annotations

import os
import re
import threading
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import ArrayLike, NDArray

PRODUCT = "ldem_75s_240m"
BASE_URL = ("https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/"
            "data/lola_gdr/polar/img/")
LOLA_DIR_ENV = "LUNA_LOLA_DIR"
AUTO_DOWNLOAD_ENV = "LUNA_LOLA_AUTO_DOWNLOAD"     # "0" disables download-on-first-use
DEFAULT_DIR = Path(__file__).resolve().parent.parent / "data" / "lola"
SPHERE_M = 1737400.0
USER_AGENT = "luna-nav-ai-visibility-planner/1.2"

_lock = threading.Lock()
_cache: dict[Path, "LolaDEM"] = {}


class TerrainError(RuntimeError):
    """LOLA data missing/unreachable, or a site outside the DEM coverage."""

    def __init__(self, message: str, code: str = "TERRAIN_UNAVAILABLE") -> None:
        super().__init__(message)
        self.code = code


def lola_dir(path: str | Path | None = None) -> Path:
    return Path(path) if path else Path(os.environ.get(LOLA_DIR_ENV) or DEFAULT_DIR)


def _urlopen(url: str, timeout: float = 120.0, start_byte: int = 0):
    """HTTPS GET using the OS certificate store when available (the PDS server's chain needs it)."""
    try:
        import truststore
        truststore.inject_into_ssl()
    except ImportError:
        pass
    headers = {"User-Agent": USER_AGENT}
    if start_byte:
        headers["Range"] = f"bytes={start_byte}-"
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout)


def _get_range(url: str, part: Path, start: int, end: int, attempts: int = 40) -> None:
    """Fetch bytes [start, end] into ``part``, resuming after stalls/drops via HTTP Range."""
    want = end - start + 1
    for _ in range(attempts):
        have = part.stat().st_size if part.exists() else 0
        if have >= want:
            return
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                       "Range": f"bytes={start + have}-{end}"})

            with urllib.request.urlopen(req, timeout=60) as r, open(part, "ab") as f:
                if r.status != 206:
                    raise TerrainError("server does not support HTTP Range requests")
                while chunk := r.read(256 * 1024):
                    f.write(chunk)
        except (OSError, TimeoutError):
            continue
    if not part.exists() or part.stat().st_size < want:
        raise TerrainError(f"range {start}-{end} of {url} did not complete")


def _resumable_get(url: str, dest: Path, size: int, progress: bool, workers: int = 8) -> None:
    """Parallel, resumable download (the PDS server is slow per connection: ~5 KB/s observed).

    Keeps any existing prefix in ``dest``; splits the rest into ``workers`` HTTP Range requests
    that each resume on their own after a stall, then concatenates.
    """
    from concurrent.futures import ThreadPoolExecutor

    try:
        import truststore
        truststore.inject_into_ssl()
    except ImportError:
        pass
    have = dest.stat().st_size if dest.exists() else 0
    if have >= size:
        return
    bounds = np.linspace(have, size, workers + 1).astype(int)
    parts = [(dest.with_name(f"{dest.name}.{k}"), int(bounds[k]), int(bounds[k + 1]) - 1)
             for k in range(workers) if bounds[k + 1] > bounds[k]]
    with ThreadPoolExecutor(len(parts)) as ex:
        futs = [ex.submit(_get_range, url, p, a, b) for p, a, b in parts]
        while progress and not all(f.done() for f in futs):
            got = have + sum(p.stat().st_size for p, _, _ in parts if p.exists())
            print(f"\r{dest.name}: {got / 1048576:.1f} / {size / 1048576:.1f} MB", end="", flush=True)
            time.sleep(2)
        for f in futs:
            f.result()
    with open(dest, "ab") as out:
        for p, _, _ in parts:
            out.write(p.read_bytes())
            p.unlink()


def download(directory: str | Path | None = None, product: str = PRODUCT,
             progress: bool = False) -> Path:
    """Download the .lbl and .img once (skips files already complete). Returns the .img path."""
    d = lola_dir(directory)
    d.mkdir(parents=True, exist_ok=True)
    try:
        lbl = d / f"{product}.lbl"
        if not lbl.exists():
            with _urlopen(BASE_URL + lbl.name) as r:
                lbl.write_bytes(r.read())
        label = parse_label(lbl.read_text(encoding="latin-1"))
        img = d / f"{product}.img"
        want = label["RECORD_BYTES"] * label["FILE_RECORDS"]
        if img.exists() and img.stat().st_size == want:
            return img
        tmp = img.with_suffix(".img.part")
        _resumable_get(BASE_URL + img.name, tmp, want, progress)
        if progress:
            print()
        if tmp.stat().st_size != want:
            tmp.unlink()
            raise TerrainError(f"incomplete download of {img.name}")
        tmp.replace(img)
        return img
    except TerrainError:
        raise
    except Exception as e:  # noqa: BLE001 - network/TLS/OS errors all mean "unavailable"
        raise TerrainError(f"could not download NASA LOLA {product} from {BASE_URL}: {e}") from e


def parse_label(text: str) -> dict:
    """The few PDS3 label keywords needed to read the grid."""
    def num(key: str) -> float:
        m = re.search(rf"^\s*{key}\s*=\s*([-+0-9.]+)", text, re.M)
        if not m:
            raise TerrainError(f"PDS label missing {key}")
        return float(m.group(1))
    out = {k: int(num(k)) for k in ("LINES", "LINE_SAMPLES", "SAMPLE_BITS", "RECORD_BYTES",
                                    "FILE_RECORDS")}
    out.update(SCALING_FACTOR=num("SCALING_FACTOR"), MAP_SCALE=num("MAP_SCALE"),
               CENTER_LATITUDE=num("CENTER_LATITUDE"), MAXIMUM_LATITUDE=num("MAXIMUM_LATITUDE"),
               A_AXIS_RADIUS=num("A_AXIS_RADIUS"))
    stype = re.search(r'^\s*SAMPLE_TYPE\s*=\s*"?(\w+)', text, re.M)
    out["SAMPLE_TYPE"] = stype.group(1) if stype else ""
    return out


@dataclass
class LolaDEM:
    """Memory-mapped LOLA polar DEM with bilinear height lookup (meters above 1737.4 km)."""

    path: Path
    label: dict
    data: NDArray[np.int16]

    @classmethod
    def open(cls, directory: str | Path | None = None, product: str = PRODUCT,
             auto_download: bool | None = None) -> "LolaDEM":
        d = lola_dir(directory).resolve()
        img = d / f"{product}.img"
        with _lock:
            if img in _cache:
                return _cache[img]
            if auto_download is None:
                auto_download = os.environ.get(AUTO_DOWNLOAD_ENV, "1") != "0"
            lbl = d / f"{product}.lbl"
            if not (img.exists() and lbl.exists()):
                if not auto_download:
                    raise TerrainError(f"NASA LOLA {product} not found in {d}. "
                                       "Run `python scripts/fetch_lola.py`.")
                download(d, product)
            label = parse_label(lbl.read_text(encoding="latin-1"))
            if label["SAMPLE_TYPE"] != "LSB_INTEGER" or label["SAMPLE_BITS"] != 16:
                raise TerrainError(f"unsupported LOLA sample type {label['SAMPLE_TYPE']}")
            if label["CENTER_LATITUDE"] != -90 or label["A_AXIS_RADIUS"] != 1737.4:
                raise TerrainError("expected a south-polar LOLA grid on the 1737.4 km sphere")
            n = label["LINES"]
            if img.stat().st_size != n * label["LINE_SAMPLES"] * 2:
                raise TerrainError(f"{img.name} has the wrong size; delete it and re-download")
            data = np.memmap(img, dtype="<i2", mode="r", shape=(n, label["LINE_SAMPLES"]))
            dem = cls(img, label, data)
            _cache[img] = dem
            return dem

    @property
    def n(self) -> int:
        return int(self.label["LINES"])

    @property
    def scale_m(self) -> float:
        return float(self.label["MAP_SCALE"])

    @property
    def max_lat_deg(self) -> float:
        """Northern edge of guaranteed coverage (e.g. -75)."""
        return float(self.label["MAXIMUM_LATITUDE"])

    # -------------------------------------------------------------- projection (PDS DSMAP)
    def latlon_to_pixel(self, lat_deg: ArrayLike, lon_deg: ArrayLike) -> tuple[NDArray, NDArray]:
        """(sample I, line J), 1-based, fractional. Inverse of the catalog's forward equations."""
        lat = np.radians(np.asarray(lat_deg, dtype=float))
        lon = np.radians(np.asarray(lon_deg, dtype=float))
        r = 2.0 * SPHERE_M * np.tan((np.pi / 2 - np.abs(lat)) / 2.0)
        x, y = r * np.sin(lon), r * np.cos(lon)
        c = self.n / 2.0 + 0.5
        return x / self.scale_m + c, c - y / self.scale_m

    def pixel_to_latlon(self, i: ArrayLike, j: ArrayLike) -> tuple[NDArray, NDArray]:
        """Forward equations of DSMAP_POLAR.CAT for the southern hemisphere (NS = -1)."""
        c = self.n / 2.0 + 0.5
        x = (np.asarray(i, dtype=float) - c) * self.scale_m
        y = -(np.asarray(j, dtype=float) - c) * self.scale_m
        lon = np.degrees(np.arctan2(x, y))
        lat = -90.0 + np.degrees(2.0 * np.arctan(0.5 * np.hypot(x, y) / SPHERE_M))
        return lat, lon

    def height_m(self, lat_deg: ArrayLike, lon_deg: ArrayLike) -> NDArray[np.float64]:
        """Bilinear height (m above the 1737.4 km sphere); NaN outside the grid."""
        i, j = self.latlon_to_pixel(lat_deg, lon_deg)
        x, y = np.asarray(i) - 1.0, np.asarray(j) - 1.0      # 0-based column / row
        x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
        ok = (x0 >= 0) & (y0 >= 0) & (x0 < self.n - 1) & (y0 < self.n - 1)
        x0c, y0c = np.clip(x0, 0, self.n - 2), np.clip(y0, 0, self.n - 2)
        fx, fy = x - x0c, y - y0c
        d = self.data
        h = ((d[y0c, x0c] * (1 - fx) + d[y0c, x0c + 1] * fx) * (1 - fy)
             + (d[y0c + 1, x0c] * (1 - fx) + d[y0c + 1, x0c + 1] * fx) * fy)
        return np.where(ok, h * self.label["SCALING_FACTOR"], np.nan)

    def source_text(self) -> str:
        return (f"NASA LRO LOLA {self.path.stem.upper()} (PDS Geosciences, "
                f"{self.scale_m:.0f} m/pixel, heights above 1737.4 km sphere)")
