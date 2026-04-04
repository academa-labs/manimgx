"""Recorded methods keep their arguments as written and start when played; tweens that begin
together on one mobject compose; a replacement leaves its target in its mobject's place.

- `.animate` and `ApplyMethod` take their arguments as written, and carry the calls out on the
  mobject as it is when the animation begins.
- An animation's `keys` (functions of the mobject) are applied when it begins, to a copy.
- A mobject's override (`override_animation`) plays in place of the animation it overrides,
  the animation given in a list or a generator too.
- Moves compose: shifts and turns, and a scaling about the mobject's center, played together
  end where applying them one after another puts it, whatever their order. (Changes of shape
  add: two scalings played together add their changes, as two morphs do; a scaling is not a
  step of a motion, as a turn is.)
- Paint composes channel by channel: a fade and a recolor played together both happen, the
  same in either order.
- Played, a transform made to replace its mobject (`replace_mobject_with_target_in_scene`, as
  a scene gives it) leaves the scene holding its target where the mobject was; one with no
  target of its own leaves the mobject (a remover, nothing): never an object of its own making.
"""

from collections.abc import Callable, Iterator

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st
from tests.scenes import Recorder, assert_same_frames, record, scene
from tests.strategies import vectors

import manimgx as m
from manimgx.animation import easing as rf
from manimgx.animation.transform import TransformOptions
from manimgx.drawing.paint import mix_rgba


@pytest.mark.parametrize("form", ["animate", "positional", "keyword"])
def test_recorded_calls_snapshot_arguments_but_replay_on_the_current_mobject(
    form: str,
) -> None:
    square = m.Square()
    destination = m.Dot(2 * m.RIGHT + m.UP)
    wanted = destination.get_center().copy()
    animation: m.Animation
    if form == "animate":
        animation = square.animate.move_to(destination)
    elif form == "positional":
        animation = m.ApplyMethod(square.move_to, destination)
    else:
        animation = m.ApplyMethod(square.move_to, {"point_or_mobject": destination})
    destination.shift(3 * m.UP)
    square.shift(2 * m.LEFT)
    start = square.get_center().copy()

    animation.begin()
    animation.interpolate(0)
    np.testing.assert_allclose(square.get_center(), start, atol=1e-12)
    animation.finish()
    np.testing.assert_allclose(square.get_center(), wanted, atol=1e-12)


def test_keys_are_applied_as_the_animation_begins_to_a_copy() -> None:
    square = m.Square()
    copies: list[m.Mobject] = []

    def moved(copy: m.Mobject) -> m.Mobject:
        copies.append(copy)
        return copy.shift(2 * m.RIGHT)

    animation = m.Transform(square, keys=(None, moved), rate_func=rf.linear)
    assert copies == []
    animation.begin()
    assert len(copies) == 1
    assert copies[0] is not square
    animation.interpolate(0.5)
    np.testing.assert_allclose(square.get_center(), m.RIGHT)
    animation.finish()
    np.testing.assert_allclose(square.get_center(), 2 * m.RIGHT)


def test_an_override_plays_in_place_of_its_animation_given_in_iterables() -> None:
    class Waiting(m.Square):
        @m.override_animation(m.FadeIn)
        def _fade_in(self) -> m.Animation:
            return m.Wait(0.25)

    def given() -> Iterator[m.Animation]:
        yield m.FadeIn(Waiting())

    group = m.AnimationGroup(given(), [m.FadeIn(Waiting())], m.FadeIn(m.Square()))
    kinds = [type(part) for part in group.animations]
    assert kinds == [m.Wait, m.Wait, m.FadeIn]


moves = st.lists(
    st.one_of(
        st.tuples(st.just("shift"), vectors(bound=3).map(lambda v: v * [1, 1, 0])),
        st.tuples(st.just("rotate"), st.floats(-3, 3)),
        st.tuples(st.just("scale"), st.floats(0.3, 3)),
    ),
    min_size=1,
    max_size=3,
).filter(lambda calls: sum(name == "scale" for name, _ in calls) <= 1)


def played(calls: list[tuple[str, object]], reverse: bool) -> np.ndarray:
    def tell(s: Recorder) -> None:
        square = m.Square(1.5).shift(0.3 * m.LEFT)
        s.stage = [square]
        s.add(square)
        anims = [getattr(square.animate, name)(arg) for name, arg in calls]
        s.play(*(anims[::-1] if reverse else anims))

    return record(tell).stage[0].points


@given(calls=moves, reverse=st.booleans())
def test_moves_played_together_end_as_applied_in_turn(
    calls: list[tuple[str, object]], reverse: bool
) -> None:
    square = m.Square(1.5).shift(0.3 * m.LEFT)
    for name, arg in calls:
        getattr(square, name)(arg)
    np.testing.assert_allclose(played(calls, reverse), square.points, atol=1e-9)


def faded_and_recolored(recolor_first: bool) -> Recorder:
    def tell(s: Recorder) -> None:
        square = m.Square(color=m.BLUE, fill_opacity=1)
        s.stage = [square]
        anims = [m.FadeIn(square), square.animate.set_color(m.RED)]
        s.play(*(anims[::-1] if recolor_first else anims), rate_func=rf.linear)

    return record(tell)


def test_a_fade_and_a_recolor_both_happen_in_either_order() -> None:
    first, other = faded_and_recolored(False), faded_and_recolored(True)
    assert_same_frames(first.frames, other.frames)
    halfway = first.frames[5][0]
    fill = np.frombuffer(halfway.brushes[0], dtype=float).reshape(-1, 4)
    color = mix_rgba(m.ManimColor(m.BLUE).to_rgba(), m.ManimColor(m.RED).to_rgba(), 0.5)
    np.testing.assert_allclose(fill[0, :3], color[:3], atol=1e-9)
    assert fill[0, 3] == pytest.approx(0.5)


REPLACE: TransformOptions = {"replace_mobject_with_target_in_scene": True}
# each: a transform of a square made to replace it (given the circle it may turn into)
REPLACING: dict[str, Callable[[m.Square, m.Circle], m.Transform]] = {
    "Transform": lambda sq, c: m.Transform(sq, c, **REPLACE),
    "ReplacementTransform": lambda sq, c: m.ReplacementTransform(sq, c),
    "Transform through keys": lambda sq, c: m.Transform(
        sq, c, keys=(None, lambda copy: copy.shift(m.RIGHT)), **REPLACE
    ),
    ".animate": lambda sq, c: sq.animate(**REPLACE).shift(m.RIGHT),
    "Rotate": lambda sq, c: m.Rotate(sq, 1.0, **REPLACE),
    "FadeIn": lambda sq, c: m.FadeIn(sq, **REPLACE),
    "FadeOut": lambda sq, c: m.FadeOut(sq, **REPLACE),
    "Indicate": lambda sq, c: m.Indicate(sq, **REPLACE),
    "GrowFromPoint": lambda sq, c: m.GrowFromPoint(sq, m.LEFT, **REPLACE),
    "ApplyMethod": lambda sq, c: m.ApplyMethod(sq.shift, m.RIGHT, **REPLACE),
    "ApplyFunction": lambda sq, c: m.ApplyFunction(
        lambda copy: copy.shift(m.RIGHT), sq, **REPLACE
    ),
    "MoveAlongPath": lambda sq, c: m.MoveAlongPath(
        sq, m.Line(m.LEFT, m.RIGHT), **REPLACE
    ),
    "Create": lambda sq, c: m.Create(sq, **REPLACE),
    "DrawBorderThenFill": lambda sq, c: m.DrawBorderThenFill(sq, **REPLACE),
    "CyclicReplace": lambda sq, c: m.CyclicReplace(sq, **REPLACE),
}


@pytest.mark.parametrize("name", sorted(REPLACING))
def test_a_replacement_leaves_its_target_in_its_mobjects_place(name: str) -> None:
    square, circle = m.Square(), m.Circle().shift(m.RIGHT)
    before, after = m.Dot(m.UP), m.Dot(m.DOWN)
    animation = REPLACING[name](square, circle)
    target = animation.target_mobject  # its own, if it has one

    def construct(s: m.Scene) -> None:
        s.add(before, square, after)
        s.play(animation)

    told = scene(construct)
    told.render()
    if target is not None:
        middle = [target]
    else:
        middle = [] if animation.is_remover() else [square]
    assert [id(x) for x in told.mobjects] == [id(x) for x in (before, *middle, after)]
