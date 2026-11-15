"""Visibility windows from sampled 'margin' series. Pure NumPy, no SPICE.

margin(t) = body elevation - horizon elevation at the body's azimuth (deg); the body is visible
when margin > 0. Between two samples where the sign changes there is a rise or set. We first
estimate the crossing by linear interpolation, then (optionally) refine it by bisection on the
true margin function so the window edges are far more precise than the sampling step.
Limitation: a rise AND set both inside one sampling step are not detected (use a smaller step).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
from numpy.typing import ArrayLike

MarginFn = Callable[[float], float]
BracketFn = Callable[[float, float], float]


@dataclass(frozen=True)
class Interval:
    """[start, end] in the same time unit as the input (seconds in this package).

    starts_at_interval_start / ends_at_interval_end: the window was cut by the analysis interval
    (the body was already visible at the start or still visible at the end).
    """

    start: float
    end: float
    starts_at_interval_start: bool = False
    ends_at_interval_end: bool = False

    @property
    def duration(self) -> float:
        return self.end - self.start


def _crossing(t0: float, t1: float, m0: float, m1: float, refine: MarginFn | None,
              tol: float, refine_bracket: BracketFn | None = None) -> float:
    """Time where margin crosses 0 between (t0, m0) and (t1, m1)."""
    if refine_bracket is not None:
        return float(min(max(refine_bracket(t0, t1), t0), t1))
    guess = t0 + (t1 - t0) * m0 / (m0 - m1) if m0 != m1 else 0.5 * (t0 + t1)
    if refine is None:
        return float(guess)
    lo, hi, mlo = t0, t1, m0
    for _ in range(64):
        if hi - lo <= tol:
            break
        mid = 0.5 * (lo + hi)
        mm = refine(mid)
        if (mm > 0) == (mlo > 0):
            lo, mlo = mid, mm
        else:
            hi = mid
    return 0.5 * (lo + hi)


def find_windows(t: ArrayLike, margin: ArrayLike, refine: MarginFn | None = None,
                 tol: float = 1.0, refine_bracket: BracketFn | None = None) -> list[Interval]:
    """Intervals where margin > 0.

    Args:
        t: strictly increasing sample times (seconds).
        margin: margin at each sample (deg), same length as t.
        refine: optional exact margin function f(t) used for bisection refinement.
        tol: bisection tolerance in the units of t (default 1 s).
        refine_bracket: optional f(t0, t1) -> crossing time inside [t0, t1]; used instead of
            ``refine`` when the data source refines a whole bracket at once (e.g. one dense
            Horizons query).
    """
    t = np.asarray(t, dtype=float)
    m = np.asarray(margin, dtype=float)
    if t.ndim != 1 or t.shape != m.shape or t.size < 2:
        raise ValueError("t and margin must be 1-D arrays of equal length >= 2")
    if np.any(np.diff(t) <= 0):
        raise ValueError("t must be strictly increasing")
    vis = m > 0
    out: list[Interval] = []
    start = float(t[0]) if vis[0] else None
    cut = bool(vis[0])  # current window began at the interval start
    for i in np.nonzero(vis[1:] != vis[:-1])[0]:
        tc = _crossing(t[i], t[i + 1], m[i], m[i + 1], refine, tol, refine_bracket)
        if vis[i + 1]:
            start, cut = tc, False
        else:
            out.append(Interval(float(start), tc, starts_at_interval_start=cut))
            start, cut = None, False
    if start is not None:
        out.append(Interval(float(start), float(t[-1]), starts_at_interval_start=cut,
                            ends_at_interval_end=True))
    return out


def complement(windows: list[Interval], t_start: float, t_end: float) -> list[Interval]:
    """Gaps between windows within [t_start, t_end] (e.g. darkness = complement of sunlight)."""
    gaps: list[Interval] = []
    cursor = t_start
    for w in windows:
        if w.start > cursor:
            gaps.append(Interval(cursor, w.start, starts_at_interval_start=cursor == t_start))
        cursor = max(cursor, w.end)
    if cursor < t_end:
        gaps.append(Interval(cursor, t_end, starts_at_interval_start=cursor == t_start,
                             ends_at_interval_end=True))
    return gaps


def total_duration(windows: list[Interval]) -> float:
    """Sum of window durations."""
    return float(sum(w.duration for w in windows))


def longest(windows: list[Interval]) -> float:
    """Longest window duration (0 if none)."""
    return max((w.duration for w in windows), default=0.0)
