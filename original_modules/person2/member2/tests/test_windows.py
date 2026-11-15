"""Window finding on synthetic series (pure NumPy, no SPICE)."""
import numpy as np
import pytest

from visibility_planner.windows import complement, find_windows, longest, total_duration

PERIOD = 1000.0


def sine(t):
    return np.sin(2 * np.pi * np.asarray(t) / PERIOD)


def test_sine_known_crossings_linear():
    t = np.linspace(-100, 2100, 221)  # step 10
    w = find_windows(t, sine(t))
    starts = [x.start for x in w]
    ends = [x.end for x in w]
    np.testing.assert_allclose(starts, [0, 1000, 2000], atol=0.5)
    np.testing.assert_allclose(ends, [500, 1500, 2100], atol=0.5)
    assert w[-1].ends_at_interval_end and not w[0].starts_at_interval_start


def test_refinement_error_much_smaller_than_step():
    t = np.arange(0.0, 3000.0, 97.0)  # deliberately coarse, step 97
    lin = find_windows(t, sine(t) + 0.3)
    ref = find_windows(t, sine(t) + 0.3, refine=lambda x: float(sine(x) + 0.3), tol=1e-3)
    exact_start = PERIOD * (1 - np.arcsin(0.3) / (2 * np.pi))  # first rise after a set
    rise = [w.start for w in ref if not w.starts_at_interval_start][0]
    assert abs(rise - exact_start) < 1e-2
    assert abs(rise - exact_start) < 97.0
    rise_lin = [w.start for w in lin if not w.starts_at_interval_start][0]
    assert abs(rise - exact_start) < abs(rise_lin - exact_start)


def test_always_visible_one_window_cut_both_sides():
    t = np.arange(0, 100.0)
    (w,) = find_windows(t, np.full_like(t, 2.0))
    assert (w.start, w.end) == (0, 99) and w.starts_at_interval_start and w.ends_at_interval_end
    assert complement([w], 0, 99) == []


def test_never_visible_is_one_gap():
    t = np.arange(0, 100.0)
    assert find_windows(t, -np.ones_like(t)) == []
    (g,) = complement([], 0, 99)
    assert g.duration == 99 and g.starts_at_interval_start and g.ends_at_interval_end


def test_window_cut_by_interval_start_and_end():
    t = np.linspace(0, 10, 11)
    m = np.array([1, 1, 1, -1, -1, -1, -1, 1, 1, 1, 1], float)
    w = find_windows(t, m)
    assert len(w) == 2
    assert w[0].starts_at_interval_start and not w[0].ends_at_interval_end
    assert w[1].ends_at_interval_end and not w[1].starts_at_interval_start
    assert w[0].end == pytest.approx(2.5) and w[1].start == pytest.approx(6.5)


def test_crossing_exactly_on_first_sample_not_flagged_as_cut():
    w = find_windows([0, 1, 2], [0.0, 1.0, 1.0])
    assert not w[0].starts_at_interval_start


def test_complement_and_totals_partition_interval():
    t = np.linspace(0, 3000, 301)
    w = find_windows(t, sine(t))
    g = complement(w, 0, 3000)
    assert total_duration(w) + total_duration(g) == pytest.approx(3000)
    assert longest(g) == pytest.approx(500, abs=1)


def test_bad_inputs_rejected():
    with pytest.raises(ValueError):
        find_windows([0, 1], [1.0])
    with pytest.raises(ValueError):
        find_windows([0, 0], [1.0, 1.0])
