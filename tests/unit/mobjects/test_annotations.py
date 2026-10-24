"""A rectangle surrounding mobjects is their box grown by its buffer on each side, at their
center. A brace changes nothing of what it braces, to the bit; an arc's brace is made from the
arc as it is: of a turned and moved arc, it is the arc's brace turned and moved."""

import numpy as np
from hypothesis import given
from hypothesis import strategies as st
from tests.strategies import drawn

import manimgx as m


@given(
    targets=st.lists(drawn, min_size=1, max_size=2),
    buff=st.floats(0, 1) | st.tuples(st.floats(0, 1), st.floats(0, 1)),
)
def test_a_surrounding_rectangle_is_the_box_grown_by_its_buffer(
    targets: list[m.Mobject], buff: float | tuple[float, float]
) -> None:
    box = m.Group(*targets).boundary_box()
    assert box is not None
    grown = np.array(buff if isinstance(buff, tuple) else (buff, buff))
    rectangle = m.SurroundingRectangle(*targets, buff=buff)
    tolerance = 1e-9 * (1 + np.abs(box).max())
    np.testing.assert_allclose(
        rectangle.get_corner(m.DL)[:2], box[0, :2] - grown, atol=tolerance
    )
    np.testing.assert_allclose(
        rectangle.get_corner(m.UR)[:2], box[1, :2] + grown, atol=tolerance
    )
    np.testing.assert_allclose(rectangle.get_center(), box.mean(axis=0), atol=tolerance)


@given(direction=st.sampled_from([m.DOWN, m.UR, m.LEFT, 2 * m.UP + m.RIGHT]))
def test_a_brace_changes_nothing_of_what_it_braces(direction: np.ndarray) -> None:
    braced = m.Square().rotate(0.3).shift(m.RIGHT)
    before = braced.points.copy()
    m.Brace(braced, direction=direction)
    assert np.array_equal(braced.points, before)


@given(angle=st.floats(-3, 3), shift=st.tuples(st.floats(-2, 2), st.floats(-2, 2)))
def test_an_arcs_brace_is_made_from_the_arc_as_it_is(
    angle: float, shift: tuple[float, float]
) -> None:
    arc = m.Arc(radius=1.5, start_angle=0.3, angle=1.6)
    vector = np.array([*shift, 0.0])
    moved = arc.copy().rotate(angle, about_point=m.ORIGIN).shift(vector)
    made = m.ArcBrace(moved)
    carried = m.ArcBrace(arc).rotate(angle, about_point=m.ORIGIN).shift(vector)
    np.testing.assert_allclose(made.points, carried.points, atol=1e-9)
