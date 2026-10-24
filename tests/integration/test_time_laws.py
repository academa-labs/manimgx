"""Laws of time: what a scene shows does not depend on how the engine computes it.

- A copy of an updating mobject evolves as its original does.
- A member's updaters run as often however many groups of one family share it.
- Time out of the scene is not made up, whichever way a mobject joins it.
- A `ChangeSpeed` warps its updaters' clock over its own window, wherever it is nested.
"""

from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import manimgx as m
from manimgx.mobject import flow
from manimgx.settings import config

LAWS = settings(
    max_examples=80, deadline=None, suppress_health_check=[HealthCheck.too_slow]
)


# ── what makes a mobject update ──────────────────────────────────────────────────────────
TAKING_TIME = ["push", "spring", "spin", "orbit", "drift", "boundary", "speed"]


class Spring:
    """A simulated spring toward the origin: an updater whose velocity is its own state."""

    def __init__(self, stiffness: float) -> None:
        self.stiffness, self.velocity = stiffness, np.zeros(3)

    def __call__(self, mob: m.Mobject, dt: float) -> None:
        self.velocity = self.velocity - dt * self.stiffness * mob.get_center()
        mob.shift(dt * self.velocity)


@dataclass(frozen=True)
class Actor:
    """An updater of one stage mobject (`on`), which may read another (`reads`)."""

    kind: str
    on: int
    reads: int
    rate: float

    def attach(self, stage: list[m.Mobject]) -> m.Mobject | None:
        """Make `stage[on]` update; a mobject of its own the story adds too (a trace, an
        outline), if any."""
        mob, other = stage[self.on % len(stage)], stage[self.reads % len(stage)]
        r = self.rate
        match self.kind:
            case "push":
                mob.add_updater(lambda x, dt: x.shift(dt * r * m.RIGHT))
            case "spring":
                mob.add_updater(Spring(r))
            case "spin":
                m.always_rotate(mob, r)
            case "orbit":
                m.always_rotate(mob, r, about_point=m.ORIGIN)
            case "drift":
                m.always_shift(mob, m.UP, r / 2)
            case "follow":
                mob.add_updater(lambda x: x.move_to(other.get_center() + m.UP))
            case "nudge":
                mob.add_updater(lambda x: x.shift(0.01 * r * m.RIGHT))
            case "boundary":
                return m.AnimatedBoundary(other, cycle_rate=r)
            case "cycle":
                m.turn_animation_into_updater(
                    m.Rotate(mob, r, run_time=0.7), cycle=True
                )
            case "trace":
                return m.TracedPath(other.get_center, stroke_width=3)
            case "speed":
                m.ChangeSpeed.add_updater(mob, lambda x, dt: x.shift(dt * r * m.DOWN))
        return None


# ── telling a story, and what each frame shows ───────────────────────────────────────────
type Look = tuple[bytes, ...]
type Film = dict[Fraction, tuple[Look, ...]]


# ── stories ──────────────────────────────────────────────────────────────────────────────
# a turn about a point fixed in space ("orbit"; "cycle", a Rotate played over and over, which
# sets the mobject from its keyframes), and the other motions that take time
# ── the laws ─────────────────────────────────────────────────────────────────────────────
@LAWS
@given(
    kinds=st.lists(st.sampled_from(TAKING_TIME), min_size=1, max_size=2),
    before=st.sampled_from([0.0, 0.3, 0.5]),
    speeds=st.dictionaries(
        st.sampled_from([0.25, 0.5, 0.75]), st.sampled_from([0.5, 1.0, 2.0]), max_size=2
    ),
)
def test_a_copy_evolves_as_its_original(
    kinds: list[str], before: float, speeds: dict[float, float]
) -> None:
    """A copy of an updating mobject, made at an instant and added beside it, shows what the
    original shows at every frame after: it runs the same updaters, on itself, on the scene's
    clocks."""
    pair: list[m.Mobject] = []
    seen: list[tuple[np.ndarray, np.ndarray]] = []

    class Told(m.Scene):
        def construct(self) -> None:
            original = m.Square(0.5)
            for kind in kinds:
                if (extra := Actor(kind, 0, 0, 1.0).attach([original])) is not None:
                    self.add(extra)
            self.add(original)
            if before:
                self.wait(before)
            pair[:] = [original, original.copy()]
            self.add(pair[1])
            self.play(m.ChangeSpeed(m.Wait(1), speeds))
            self.wait(0.5)

        def _emit(self, repeat: int = 1) -> None:
            if pair:
                seen.append((np.array(pair[0].points), np.array(pair[1].points)))
            super()._emit(repeat)

    Told().render()
    for k, (a, b) in enumerate(seen):
        assert a.shape == b.shape, f"frame {k}: {len(a)} points, not {len(b)}"
        assert np.allclose(a, b, atol=1e-9), f"frame {k}: {a[:1]} vs {b[:1]}"


def _runs(depth: int, fan: int, members: int, shared: bool) -> list[int]:
    """How often each member's per-frame updater ran over a wait, in a family `depth` groups
    deep, each holding `fan` groups; the members are in every group of the last level
    (`shared`), or each group has members of its own."""
    runs: list[int] = []

    def member(i: int) -> m.Mobject:
        dot = m.Dot()
        dot.add_updater(lambda d: runs.append(i))
        return dot

    if shared:
        common = [member(i) for i in range(members)]

    def group(level: int) -> m.Mobject:
        if level == 0:
            return m.VGroup(
                *(common if shared else [member(i) for i in range(members)])
            )
        return m.VGroup(*(group(level - 1) for _ in range(fan)))

    root = group(depth)

    class Told(m.Scene):
        def construct(self) -> None:
            self.add(root)
            self.wait(0.3)

    Told().render()
    return [runs.count(i) for i in range(members)]


@settings(max_examples=40, deadline=None)
@given(depth=st.integers(1, 3), fan=st.integers(1, 3), members=st.integers(1, 3))
def test_a_member_updates_as_often_however_it_is_shared(
    depth: int, fan: int, members: int
) -> None:
    """A member's per-frame updaters run once a frame, wherever it is: shared by every group of
    a family, it runs as often as a member of one group does."""
    alone = _runs(depth, fan, members, shared=False)
    groups = fan**depth  # (members of their own: each group's run, as many times)
    assert _runs(depth, fan, members, shared=True) == [n // groups for n in alone]


ENTRIES: dict[str, Callable[[m.Scene, m.Mobject, m.Mobject], object]] = {
    "add": lambda s, new, old: s.add(new),
    "add_foreground": lambda s, new, old: s.add_foreground_mobjects(new),
    "bring_to_back": lambda s, new, old: s.bring_to_back(new),
    "replace": lambda s, new, old: s.replace(old, new),
    "fade_in": lambda s, new, old: s.play(m.FadeIn(new), run_time=0.2),
    "animated": lambda s, new, old: s.play(new.animate.shift(m.UP), run_time=0.2),
}


@settings(max_examples=40, deadline=None)
@given(
    entry=st.sampled_from(sorted(ENTRIES)),
    away=st.sampled_from([0.3, 0.5, 1.0]),
    fps=st.sampled_from([10, 30]),
)
def test_time_out_of_the_scene_is_not_made_up(
    entry: str, away: float, fps: int
) -> None:
    """A time-based updater is handed the time its mobject is in the scene, from when it joins,
    whichever way it joins: not the time before."""
    handed: list[float] = []
    joined: list[float] = []

    class Told(m.Scene):
        def construct(self) -> None:
            old, new = m.Dot(), m.Square(0.4)
            new.add_updater(lambda mob, dt: handed.append(dt))
            self.add(old)
            self.wait(away)
            joined.append(self.time)
            ENTRIES[entry](self, new, old)
            self.wait(0.5)
            joined.append(self.time)

    saved = config.frame_rate
    config.frame_rate = fps
    try:
        Told().render()
    finally:
        config.frame_rate = saved
    assert sum(handed) == pytest.approx(joined[1] - joined[0], abs=1e-9)


@st.composite
def speed_trees(draw: st.DrawFn, depth: int = 2) -> tuple[m.Animation, float]:
    """A tree of waits, some under a constant `ChangeSpeed`, in successions; and the time the
    speed clock runs over its play: a wait's own, under a change of speed too (its wrapped
    wait plays in its length over the speed, at that speed)."""
    kind = draw(st.sampled_from(["wait", "speed", "succession"]))
    if depth == 0 or kind == "wait":
        d = draw(st.sampled_from([0.4, 0.6, 1.0]))
        return m.Wait(d), d
    if kind == "speed":
        d = draw(st.sampled_from([0.6, 1.0]))
        v = draw(st.sampled_from([0.5, 2.0]))
        return m.ChangeSpeed(m.Wait(d), {0: v, 1: v}), d
    parts = draw(st.lists(speed_trees(depth - 1), min_size=1, max_size=3))
    return m.Succession(*(a for a, _ in parts)), sum(t for _, t in parts)


@settings(max_examples=40, deadline=None)
@given(tree=speed_trees())
def test_a_change_of_speed_warps_its_own_window(
    tree: tuple[m.Animation, float],
) -> None:
    """An updater added with `ChangeSpeed.add_updater` is handed its clock's time: scene time,
    but at a `ChangeSpeed`'s speeds over its window, wherever it is nested."""
    anim, expected = tree
    handed: list[float] = []

    class Told(m.Scene):
        def construct(self) -> None:
            dot = m.Dot()
            m.ChangeSpeed.add_updater(dot, flow(lambda d, dt: handed.append(dt)))
            self.add(dot)
            self.play(anim)

    Told().render()
    assert sum(handed) == pytest.approx(expected, abs=1e-9)
