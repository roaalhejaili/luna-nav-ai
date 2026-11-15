"""Plot Sun/Earth elevation with horizon line and shaded visibility windows.

    python examples/plot_visibility.py                      # runs all scenario_*.json
    python examples/plot_visibility.py examples/scenario_1.json
Writes examples/output/<scenario>.json and examples/output/<scenario>.png.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from visibility_planner import analyze_site  # noqa: E402

OUT = HERE / "output"
COLORS = {"sun": "#d98c00", "earth": "#2a6fdb"}


def _t(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def plot(result: dict, png: Path) -> None:
    ts = result["time_series"]
    x = [_t(p["utc"]) for p in ts]
    terrain = result["horizon"]["type"] == "terrain"
    fig, axes = plt.subplots(2, 1, figsize=(11, 6.5), sharex=True)
    for ax, body in zip(axes, ("sun", "earth")):
        c = COLORS[body]
        ax.plot(x, [p[f"{body}_el_deg"] for p in ts], color=c, lw=1.6, label=f"{body} elevation")
        ax.axhline(0, color="0.35", lw=0.8, ls="--", label="geometric horizon (0 deg)")
        if terrain:
            ax.plot(x, [p[f"{body}_horizon_el_deg"] for p in ts], color="0.2", lw=1.0,
                    label=f"terrain horizon at {body} azimuth ({result['horizon']['data_status']})")
        kind = "terrain" if terrain else "geometric"
        for w in result["windows"]:
            if w["body"] == body and w["kind"] == kind:
                ax.axvspan(_t(w["start_utc"]), _t(w["end_utc"]), color=c, alpha=0.12, lw=0)
        ax.set_ylabel(f"{body} elevation (deg)")
        ax.grid(alpha=0.25)
        ax.legend(loc="upper left", fontsize=8, frameon=False)
    s = result["summary"]
    axes[0].set_title(
        f"{result['site_id']}  lat {result['location']['lat_deg']}, lon {result['location']['lon_deg_east']} E"
        f"  |  {result['visibility_definition']}  |  data_status {result['data_status']}\n"
        f"Sun visible {s['sun_visible_fraction']:.0%} geometric"
        + (f" / {s['sun_visible_fraction_terrain']:.0%} terrain" if terrain else "")
        + f"   Earth visible {s['earth_visible_fraction']:.0%} geometric"
        + (f" / {s['earth_visible_fraction_terrain']:.0%} terrain" if terrain else "")
        + "   (shaded = visible windows)", fontsize=9)
    axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    axes[1].set_xlabel("UTC")
    fig.tight_layout()
    png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(png, dpi=110)
    plt.close(fig)


def main(paths: list[str]) -> None:
    files = [Path(p) for p in paths] or sorted(HERE.glob("scenario_*.json"))
    for f in files:
        result = analyze_site(json.loads(f.read_text(encoding="utf-8"))).model_dump(mode="json")
        (OUT / f"{f.stem}.json").parent.mkdir(parents=True, exist_ok=True)
        (OUT / f"{f.stem}.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
        plot(result, OUT / f"{f.stem}.png")
        print(f"{f.stem}: {result['data_status']} {result['summary']} -> {OUT / (f.stem + '.png')}")


if __name__ == "__main__":
    main(sys.argv[1:])
