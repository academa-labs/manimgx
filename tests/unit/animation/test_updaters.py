"""An updater acts on the mobject it runs on: a replica of an updating mobject is a mobject of
its own.

- For every built-in updater (`always_redraw`, `always`, `f_always`, `always_shift`,
  `always_rotate`, `turn_animation_into_updater`, an `AnimatedBoundary`'s, `StreamLines`' flow,
  a `TracedPath`'s) and a method of the mobject's own: a replica (a copy, a target, a saved state, or a mobject that
  took the updaters over with `match_updaters`) runs them on itself, and leaves its original
  as it was.
- A replica does not keep its original alive.
- The member a mobject's own points move into (when it becomes a mobject with none, or a
  transform aligns it) is a part of it, not a replica: the mobject's updaters act on its whole
  family, so they leave the member as they leave the mobject, and run once.
"""

import gc
import random
import weakref
from collections.abc import Callable

import numpy as np
import pytest
from tests.oracles import drawing, look, value

import manimgx as m

type Updating = tuple[m.Mobject, Callable[[], object]]


def redrawn() -> Updating:
    x = m.ValueTracker(0.0)
    return m.always_redraw(lambda: m.Dot([x.get_value(), 0, 0])), lambda: x.set_value(1)


def following() -> Updating:
    dot = m.Dot(m.RIGHT)
    return m.always(m.Square().next_to, dot, m.UP), lambda: dot.shift(m.RIGHT)


def tracking() -> Updating:
    x = m.ValueTracker(0.0)
    return m.f_always(m.Square().set_x, x.get_value), lambda: x.set_value(1)


def traced() -> Updating:
    dot = m.Dot()
    return m.TracedPath(lambda: dot.get_center()), lambda: dot.shift(m.RIGHT)


def flowing() -> Updating:
    lines = m.StreamLines(
        lambda p: m.RIGHT + 0 * p, x_range=(-1, 1, 1), y_range=(-1, 1, 1)
    )
    random.seed(0)  # (where each line's flow starts)
    lines.start_animation(warm_up=False)
    return lines, lambda: None


class Stepping(m.Square):
    """A square whose updater is a method of its own, acting on itself."""

    def step(self, mob: m.Mobject, dt: float) -> None:
        self.shift(dt * m.RIGHT)


def stepping() -> Updating:
    square = Stepping()
    return square.add_updater(square.step), lambda: None


# an updating mobject, and a change of what its updaters read
UPDATING: dict[str, Callable[[], Updating]] = {
    "always_redraw": redrawn,
    "always": following,
    "f_always": tracking,
    "always_shift": lambda: (m.always_shift(m.Square(), m.RIGHT, 1.0), lambda: None),
    "always_rotate": lambda: (m.always_rotate(m.Square()), lambda: None),
    "turn_animation_into_updater": lambda: (
        m.turn_animation_into_updater(m.Rotate(m.Square(), 1.0)),
        lambda: None,
    ),
    "AnimatedBoundary": lambda: (m.AnimatedBoundary(m.Square()), lambda: None),
    "StreamLines": flowing,
    "TracedPath": traced,
    "a method of its own": stepping,
}
REPLICAS: dict[str, Callable[[m.Mobject], m.Mobject | None]] = {
    "copy": lambda mob: mob.copy(),
    "target": lambda mob: mob.generate_target(),
    "saved state": lambda mob: mob.save_state().saved_state,
    "match_updaters": lambda mob: mob.copy().clear_updaters().match_updaters(mob),
}


def cases(replicas: list[str]) -> list[tuple[str, str]]:
    return [
        (name, replica)
        for name in UPDATING
        for replica in replicas
        # match_updaters gives the same functions: a user's method stays its mobject's
        if not (name == "a method of its own" and replica == "match_updaters")
    ]


def shown(mob: m.Mobject) -> list[tuple[object, ...]]:
    """What the members with points show: not how the family is divided."""
    return drawing(mob)


@pytest.mark.parametrize("name", UPDATING)
def test_the_member_that_takes_a_mobjects_points_leaves_its_updaters_as_they_were(
    name: str,
) -> None:
    whole, change = UPDATING[name]()
    pushed, change_pushed = UPDATING[name]()
    pushed.push_self_into_submobjects()
    for mob, edit in ((whole, change), (pushed, change_pushed)):
        edit()
        mob.update(0.5)
    assert shown(pushed) == shown(whole)


def test_a_redrawn_mobject_that_becomes_empty_stays_one_family() -> None:
    """When what is redrawn has no points, the mobject's own points move into a member of
    its own; the member is a part of it, not a replica: it runs none of the updaters, so an
    update does not push the points into one member after another, without end."""
    gone = m.ValueTracker(0.0)
    shape = m.always_redraw(lambda: m.VMobject() if gone.get_value() else m.Square())
    gone.set_value(1.0)
    sizes = []
    for _ in range(4):
        shape.update(0.1)
        sizes.append(len(shape.get_family()))
    assert sizes == [sizes[0]] * 4
    assert all(not member.get_updaters() for member in shape.get_family()[1:])
    gone.set_value(0.0)
    shape.update(0.1)  # the square again, drawn by the member that holds its points
    np.testing.assert_allclose(shape.get_all_points(), m.Square().get_all_points())


@pytest.mark.parametrize(("name", "replica"), cases(list(REPLICAS)))
def test_a_replica_updates_itself_and_leaves_its_original(
    name: str, replica: str
) -> None:
    """A replica updates its own value, including a reveal window, leaving the original alone."""
    original, change = UPDATING[name]()
    clone = REPLICAS[replica](original)
    assert clone is not None
    before, start = value(original), value(clone)
    change()
    clone.update(0.5)
    assert value(clone) != start, "the replica's updaters did not run on it"
    assert value(original) == before


@pytest.mark.parametrize(("name", "replica"), cases(["copy", "match_updaters"]))
def test_a_replica_does_not_keep_its_original_alive(name: str, replica: str) -> None:
    original, change = UPDATING[name]()
    clone = REPLICAS[replica](original)
    assert clone is not None
    alive = weakref.ref(original)
    del original
    gc.collect()
    assert alive() is None
    change()
    clone.update(0.25)
    assert np.isfinite(clone.get_center()).all()


def test_a_copy_finishes_each_updater_animation_on_its_own_time() -> None:
    original = m.Square()
    m.turn_animation_into_updater(
        m.Rotate(original, m.PI / 2, run_time=0.5, rate_func=m.linear)
    )
    m.turn_animation_into_updater(
        m.Rotate(original, m.PI, run_time=1, rate_func=m.linear), delay=0.25
    )
    clone = original.copy()
    for dt, angle in ((0.5, m.PI / 4), (0.5, 3 * m.PI / 4), (0.25, m.PI)):
        clone.update(dt)
        np.testing.assert_allclose(
            clone.points, m.Square().rotate(angle).points, atol=1e-14
        )
        np.testing.assert_array_equal(original.points, m.Square().points)
    assert not clone.get_updaters()
    original.update(1.25)
    np.testing.assert_allclose(original.points, clone.points)
    assert not original.get_updaters()


@pytest.mark.parametrize("copied", [False, True])
def test_updater_animations_can_share_a_mobject_that_gains_members(
    copied: bool,
) -> None:
    shape = m.Square()
    target = m.VGroup(m.Circle(), m.Square().shift(m.RIGHT))
    m.turn_animation_into_updater(m.Transform(shape, m.Circle(), run_time=0.5))
    m.turn_animation_into_updater(m.Transform(shape, target, run_time=1))
    if copied:
        shape = shape.copy()
    for dt in (0.25, 0.25, 0.5):
        shape.update(dt)
    assert shown(shape) == shown(target)
    assert not shape.get_updaters()


@pytest.mark.parametrize("name", UPDATING)
def test_a_play_that_changes_nothing_is_a_wait(name: str) -> None:
    """A play holds what it animates, never a copy of it: beneath a play, a mobject's updaters
    run on the mobject itself, read the world as it is, and keep what they keep. So a play that
    changes nothing shows what a wait shows, frame by frame, and leaves the mobject where a
    wait leaves it."""

    def film(played: bool) -> list[list[tuple[object, ...]]]:
        mob, change = UPDATING[name]()
        seen: list[list[tuple[object, ...]]] = []

        class Story(m.Scene):
            def construct(self) -> None:
                self.add(mob)
                self.add_updater(lambda dt: change())  # what the updaters read moves on
                self.wait(0.5)
                if played:
                    self.play(m.Animation(mob))
                else:
                    self.wait(1)
                self.wait(0.5)

        Story().render(frames=lambda frame: seen.append(look(mob)))
        return seen

    assert film(played=True) == film(played=False)
