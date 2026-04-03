"""A clock's local time is scene time, warped where its warps say, and it only runs forward.

- With no warps it is scene time; over a warp it covers the warp's span, and outside every
  warp it runs at scene time's pace.
- However its warps overlap, it never runs backward and never jumps: where warps overlap, the
  one begun last rules while it lasts.
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from manimgx.animation import easing as rf
from manimgx.animation.clock import Clock

# monotone maps of [0, 1] onto itself, of bounded slope (at most 10)
PROGRESSES = [rf.linear, rf.smooth, rf.rush_into, rf.rush_from, rf.ease_out_quad, rf.double_smooth,
              rf.ease_in_sine, rf.ease_out_sine, rf.ease_in_out_cubic, rf.ease_in_expo]  # fmt: skip

Warp = tuple[float, float, float, rf.RateFunction]
warps = st.tuples(
    st.floats(0, 5), st.floats(0.05, 3), st.floats(0, 3), st.sampled_from(PROGRESSES)
)
times = st.floats(0, 12)


def clock(*ws: Warp) -> Clock:
    c = Clock()
    for w in ws:
        c.warp(*w)
    return c


@given(t=times)
def test_without_warps_it_is_scene_time(t: float) -> None:
    assert Clock().at(t) == t


@given(w=warps, t=times)
def test_over_a_warp_it_covers_the_warps_span(w: Warp, t: float) -> None:
    start, duration, span, progress = w
    local = clock(w).at(t)
    if t <= start:
        assert local == pytest.approx(t)
    elif t >= start + duration:
        assert local == pytest.approx(t - duration + span)
    else:
        assert local == pytest.approx(start + span * progress((t - start) / duration))


@given(ws=st.lists(warps, max_size=4), a=times, b=times)
def test_it_never_runs_backward(ws: list[Warp], a: float, b: float) -> None:
    a, b = sorted((a, b))
    c = clock(*ws)
    assert c.at(a) <= c.at(b) + 1e-12


@given(ws=st.lists(warps, max_size=4), t=times)
def test_it_never_jumps(ws: list[Warp], t: float) -> None:
    c, h = clock(*ws), 1e-7
    pace = max([1.0, *(10 * span / duration for _, duration, span, _ in ws)])
    assert abs(c.at(t + h) - c.at(t)) <= pace * h + 1e-12


@given(first=warps, second=warps, a=st.floats(0, 1), b=st.floats(0, 1))
def test_where_warps_overlap_the_one_begun_last_rules(
    first: Warp, second: Warp, a: float, b: float
) -> None:
    s1, d1, span1, p1 = first
    _, _, span2, p2 = second
    s2 = s1 + d1 / 4  # the second begins inside the first, and ends before it
    d2 = d1 / 2
    c = clock(first, (s2, d2, span2, p2))
    a, b = sorted((a, b))
    inside = c.at(s2 + b * d2) - c.at(s2 + a * d2)
    assert inside == pytest.approx(span2 * (p2(b) - p2(a)), abs=1e-9)
    # after it, the first rules again, at its own pace
    after = c.at(s1 + d1) - c.at(s2 + d2)
    assert after == pytest.approx(span1 * (p1(1.0) - p1(0.75)), abs=1e-9)
