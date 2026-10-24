"""Laws of time: what a scene shows does not depend on how the engine computes it.

Random stories, drawn by Hypothesis: a stage of shapes, some of them updating (pushed, a spring,
flows, a relation, a nudge each frame, an outline, a cycling animation, a trace, a clock that a
`ChangeSpeed` warps), told with plays, procedures and waits. Each law tells a story two ways
that must show the same:

- A play that changes nothing is a wait: a play holds what it animates, and the updaters
  beneath it run as they would without it.
- An observer changes nothing it does not draw: adding a traced path shows the path, and every
  other mobject as it was.
- The world at an instant does not depend on the frame rate, for updaters that take time.
- A copy of an updating mobject evolves as its original does.
- A member's updaters run as often however many groups of one family share it.
- Time out of the scene is not made up, whichever way a mobject joins it.
- A `ChangeSpeed` warps its updaters' clock over its own window, wherever it is nested.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from fractions import Fraction

import numpy as np
import pytest
from hypothesis import HealthCheck, assume, example, given, settings
from hypothesis import strategies as st
from tests.scenes import SHAPES, Leaf, Node, trees

import manimgx as m
from manimgx.mobject import flow
from manimgx.settings import config

LAWS = settings(
    max_examples=80, deadline=None, suppress_health_check=[HealthCheck.too_slow]
)


# ── what makes a mobject update ──────────────────────────────────────────────────────────
TAKING_TIME = ["push", "spring", "spin", "orbit", "drift", "boundary", "speed"]
ACTORS = [*TAKING_TIME, "cycle", "follow", "nudge", "trace"]


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


@dataclass(frozen=True)
class Step:
    """A step of a story: a wait; a play of animation trees; an actor joining; a procedure
    (`UpdateFromFunc` nudging a stage mobject each frame); or an inert step, a play of
    nothing but one stage mobject (`played`), else a wait as long."""

    kind: str  # "wait" | "play" | "join" | "procedure" | "inert"
    duration: float = 0.5
    trees: tuple[Leaf | Node, ...] = ()
    actor: Actor | None = None
    which: int = 0
    played: bool = True


@dataclass(frozen=True)
class Story:
    stage: tuple[str, ...]
    actors: tuple[Actor, ...]
    steps: tuple[Step, ...] = field(default=())

    def with_step(self, at: int, step: Step) -> "Story":
        at %= len(self.steps) + 1
        return Story(
            self.stage, self.actors, (*self.steps[:at], step, *self.steps[at:])
        )

    def tell(self, scene: m.Scene, shown: list[m.Mobject]) -> None:
        """Tell the story on `scene`: the stage (every shape added), its actors, then its
        steps; what the story shows (the stage, and what its actors add) joins `shown` as it
        is made."""
        stage = [
            SHAPES[s]().shift([i - 1.5, 0.5 * (i % 2), 0])
            for i, s in enumerate(self.stage)
        ]
        scene.add(*stage)
        shown.extend(stage)
        for actor in self.actors:
            if (extra := actor.attach(stage)) is not None:
                scene.add(extra)
                shown.append(extra)
        for step in self.steps:
            mob = stage[step.which % len(stage)]
            if step.kind == "wait":
                scene.wait(step.duration)
            elif step.kind == "play":
                scene.play(*(tree.build(stage) for tree in step.trees))
            elif step.kind == "procedure":
                nudge = m.UpdateFromFunc(mob, lambda x: x.shift(0.01 * m.RIGHT))
                scene.play(nudge, run_time=step.duration)
            elif step.kind == "inert":
                held = {id(x) for root in scene.mobjects for x in root.get_family()}
                if step.played and id(mob) in held:
                    scene.play(m.Animation(mob), run_time=step.duration)
                else:
                    scene.wait(step.duration)
            elif step.actor is not None and (extra := step.actor.attach(stage)):
                scene.add(extra)
                shown.append(extra)


# ── telling a story, and what each frame shows ───────────────────────────────────────────
type Look = tuple[bytes, ...]
type Film = dict[Fraction, tuple[Look, ...]]


def look(leaf: m.Mobject) -> Look:
    """What a leaf shows, exactly: its points and its paint."""
    p = leaf.paint
    return (
        np.asarray(leaf.points).tobytes(),
        np.asarray(p.fill).tobytes(),
        np.asarray(p.stroke).tobytes(),
        np.asarray(p.trim).tobytes(),
        np.float64(p.stroke_width).tobytes(),
    )


def film(
    tell: Callable[[m.Scene, list[m.Mobject]], None],
    fps: int = 10,
    observer: bool = False,
) -> Film:
    """Each frame's instant, and what it shows of what `tell` shows. With `observer`, the
    scene also holds a traced path of a point far away that nothing reads, added first and
    left out of what is seen."""
    shown: list[m.Mobject] = []
    frames: Film = {}

    class Told(m.Scene):
        def construct(self) -> None:
            if observer:
                far = m.Dot(3.5 * m.DOWN + 6 * m.LEFT)
                far.add_updater(lambda d, dt: d.shift(dt * m.RIGHT))
                self.add(m.TracedPath(far.get_center), far)
            tell(self, shown)

        def _emit(self, repeat: int = 1) -> None:
            drawn = {id(leaf) for leaf in self.display_list()}
            seen = tuple(
                look(leaf)
                for mob in shown
                for leaf in mob.family_members_with_points()
                if id(leaf) in drawn
            )
            for k in range(self.frame, self.frame + max(repeat, 0)):
                frames[Fraction(k, fps)] = seen
            super()._emit(repeat)

    saved = config.frame_rate
    config.frame_rate = fps
    try:
        Told().render()
    finally:
        config.frame_rate = saved
    return frames


def _points(x: Look) -> np.ndarray:
    return np.frombuffer(x[0]).reshape(-1, 3)


def assert_same_films(a: Film, b: Film) -> None:
    """The same frames, each showing the same leaves: the same paint, and the same points but
    for the last bits (a flow stepped in more pieces is exact, rounded differently)."""
    assert sorted(a) == sorted(b), "different frames"
    for t in sorted(a):
        assert len(a[t]) == len(b[t]), f"at {t} s: {len(a[t])} leaves, not {len(b[t])}"
        for i, (x, y) in enumerate(zip(a[t], b[t], strict=True)):
            assert x[1:] == y[1:], f"at {t} s, leaf {i}: paint differs"
            p, q = _points(x), _points(y)
            assert p.shape == q.shape, (
                f"at {t} s, leaf {i}: {len(p)} points, not {len(q)}"
            )
            assert np.allclose(p, q, rtol=0, atol=1e-9), (
                f"at {t} s, leaf {i}: {p[:1]} vs {q[:1]}"
            )


def assert_same_instants(a: Film, b: Film, atol: float = 1e-6) -> None:
    """At every instant both show, the same leaves at the same points."""
    common = sorted(a.keys() & b.keys())
    assert common
    for t in common:
        assert len(a[t]) == len(b[t]), f"at {t} s: {len(a[t])} leaves, not {len(b[t])}"
        for i, (x, y) in enumerate(zip(a[t], b[t], strict=True)):
            p, q = _points(x), _points(y)
            assert p.shape == q.shape, (
                f"at {t} s, leaf {i}: {len(p)} points, not {len(q)}"
            )
            assert np.allclose(p, q, atol=atol), (
                f"at {t} s, leaf {i}: {p[:1]} vs {q[:1]}"
            )


# ── stories ──────────────────────────────────────────────────────────────────────────────
PLAYED = ["shift", "turn", "recolor", "rotate", "indicate", "transform", "wait"]


def actors(stage: int, kinds: list[str]) -> st.SearchStrategy[Actor]:
    return st.builds(
        Actor,
        kind=st.sampled_from(kinds),
        on=st.integers(0, stage - 1),
        reads=st.integers(0, stage - 1),
        rate=st.sampled_from([0.5, 1.0, 2.0]),
    )


@st.composite
def stories(
    draw: st.DrawFn, kinds: list[str] = ACTORS, procedures: bool = True
) -> Story:
    """1 to 3 shapes, 1 to 3 actors, then 1 to 4 steps: waits, plays, actors joining and, if
    `procedures`, plays of a procedure."""
    stage = tuple(
        draw(st.lists(st.sampled_from(sorted(SHAPES)), min_size=1, max_size=3))
    )
    n = len(stage)
    durations = st.sampled_from([0.25, 0.5, 1.0])
    steps = [
        st.builds(Step, kind=st.just("wait"), duration=durations),
        st.builds(
            Step,
            kind=st.just("play"),
            trees=st.lists(
                trees(n, ["linear", "smooth"], PLAYED), min_size=1, max_size=2
            ).map(tuple),
        ),
        st.builds(Step, kind=st.just("join"), actor=actors(n, kinds)),
    ]
    if procedures:
        steps.append(
            st.builds(
                Step,
                kind=st.just("procedure"),
                duration=durations,
                which=st.integers(0, n - 1),
            )
        )
    cast = tuple(draw(st.lists(actors(n, kinds), min_size=1, max_size=3)))
    return Story(stage, cast, tuple(draw(st.lists(st.one_of(steps), max_size=4))))


# a turn about a point fixed in space ("orbit"; "cycle", a Rotate played over and over, which
# sets the mobject from its keyframes), and the other motions that take time
TURNS = {"orbit", "cycle"}
MOVES = {"push", "spring", "spin", "drift", "speed", *TURNS}


def commuting(story: Story) -> bool:
    """Do the motions that take time of each mobject commute? A turn about a point fixed in
    space and another motion of the same mobject do not (a move, or a turn about another
    point): taken in steps, they come to what depends on the steps, as any splitting does,
    so on the instants the scene computes, which a frame rate changes, and a traced path too
    (it steps on the simulation clock). Moves commute, and a turn about the mobject's own
    center of mass ("spin") commutes with every rigid motion, which carries that center."""
    kinds: dict[int, set[str]] = {}
    joined = [step.actor for step in story.steps if step.actor is not None]
    for actor in (*story.actors, *joined):
        kinds.setdefault(actor.on % len(story.stage), set()).add(actor.kind)
    return all(not (k & TURNS) or len(k & MOVES) == 1 for k in kinds.values())


# ── the laws ─────────────────────────────────────────────────────────────────────────────
@LAWS
@given(
    story=stories(),
    at=st.integers(0, 4),
    which=st.integers(0, 2),
    duration=st.sampled_from([0.3, 0.5, 1.0]),
)
def test_a_play_that_changes_nothing_is_a_wait(
    story: Story, at: int, which: int, duration: float
) -> None:
    """A play holds what it animates, never a copy of it: the updaters beneath it run on the
    mobject itself, read the world as it is, and keep what they keep."""
    played, waited = (
        story.with_step(at, Step("inert", duration, which=which, played=played))
        for played in (True, False)
    )
    assert_same_films(film(played.tell), film(waited.tell))


@LAWS
@given(story=stories())
@example(  # an animation turned into an updater plays beneath two tweens holding the circle
    story=Story(
        stage=("circle",),
        actors=(),
        steps=(
            Step(kind="join", actor=Actor(kind="cycle", on=0, reads=0, rate=0.5)),
            Step(kind="play", trees=(Leaf("shift", 0, v=(0.0, 0.0)), Leaf("turn", 0))),
        ),
    )
)
@example(  # a cycle ends at a frame, its time come in steps of events' exact instants
    story=Story(
        stage=("circle",),
        actors=(Actor(kind="cycle", on=0, reads=0, rate=0.5),),
        steps=(
            Step(
                kind="play",
                trees=(
                    Node(
                        "group",
                        [
                            Leaf("shift", 0, v=(0.0, 0.0)),
                            Leaf("shift", 0, v=(0.0, 0.0)),
                            Leaf("shift", 0, v=(0.0, 0.0), run_time=0.3),
                        ],
                        rate="smooth",
                    ),
                ),
            ),
        ),
    )
)
@example(  # a boundary outlines the parts its mobject has when a transform leaves it fewer
    story=Story(
        stage=("dots",),
        actors=(Actor(kind="boundary", on=0, reads=0, rate=0.5),),
        steps=(
            Step(kind="wait", duration=0.25),
            Step(
                kind="play",
                trees=(
                    Node(
                        "succession",
                        [
                            Leaf("transform", 0, v=(0.0, 0.0)),
                            Leaf("shift", 0, v=(0.0, 0.0)),
                        ],
                    ),
                ),
            ),
        ),
    )
)
def test_an_observer_changes_nothing_it_does_not_draw(story: Story) -> None:
    """A traced path of a point nothing else reads shows the path, and every other mobject as
    it was: observing runs no one else's updaters, plays or procedures again, nor in another
    order (where motions commute: see `commuting`)."""
    assume(commuting(story))
    assert_same_films(film(story.tell), film(story.tell, observer=True))


@LAWS
@given(story=stories(TAKING_TIME, procedures=False), fps=st.sampled_from([30, 60]))
@example(  # a tween begun after another restructures what they hold, which spins beneath
    story=Story(
        stage=("circle",),
        actors=(Actor(kind="spin", on=0, reads=0, rate=0.5),),
        steps=(
            Step(
                kind="play",
                trees=(
                    Leaf("shift", 0, v=(0.0, 0.5)),
                    Leaf("transform", 0, shape="dots", v=(0.0, 0.0)),
                ),
            ),
        ),
    ),
    fps=30,
)
@example(
    story=Story(
        stage=("circle",),
        actors=(Actor(kind="spin", on=0, reads=0, rate=0.5),),
        steps=(
            Step(
                kind="play",
                trees=(
                    Leaf("shift", 0, v=(0.0, 0.5)),
                    Node(
                        "group",
                        [
                            Leaf("shift", 0, v=(0.0, 0.0)),
                            Leaf("transform", 0, shape="dots", v=(0.0, 0.0)),
                        ],
                    ),
                ),
            ),
        ),
    ),
    fps=30,
)
@example(  # a boundary's outlines take its mobject's parts when a transform adds parts
    story=Story(
        stage=("circle",),
        actors=(Actor(kind="boundary", on=0, reads=0, rate=0.5),),
        steps=(
            Step(kind="wait", duration=0.25),
            Step(
                kind="play",
                trees=(
                    Leaf("shift", 0, v=(0.0, 0.0)),
                    Leaf("transform", 0, shape="dots", v=(0.0, 0.0)),
                ),
            ),
        ),
    ),
    fps=30,
)
def test_the_world_at_an_instant_does_not_depend_on_the_frame_rate(
    story: Story, fps: int
) -> None:
    """Updaters that take time step on the simulation clock or are exact (flows), and plays are
    functions of time: the world at an instant two frame rates both show is the same (where
    motions commute: see `commuting`)."""
    assume(commuting(story))
    assert_same_instants(film(story.tell, 10), film(story.tell, fps))


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
