"""A field's color queries follow its color: a uniform field answers with the color it is set
to. A stream line's colors run along it, from its start to its end."""

import numpy as np
import pytest

import manimgx as m
from manimgx.typing import Point3D


def field(kind: str, color: m.ManimColor | None = None) -> m.VectorField:
    def function(point: Point3D) -> Point3D:
        return np.array([0.2, 0.3, 0.0])

    if kind == "plain":
        return m.VectorField(function, color=color, colors=[m.RED, m.BLUE])
    if kind == "arrows":
        return m.ArrowVectorField(
            function,
            color=color,
            colors=[m.RED, m.BLUE],
            x_range=[0, 0, 1],
            y_range=[0, 0, 1],
        )
    return m.StreamLines(
        function,
        color=color,
        colors=[m.RED, m.BLUE],
        x_range=[0, 0, 1],
        y_range=[0, 0, 1],
        noise_factor=0,
        virtual_time=0.2,
    )


@pytest.mark.parametrize("kind", ["plain", "arrows", "lines"])
def test_uniform_field_color_queries_follow_its_current_color(kind: str) -> None:
    uniform = field(kind, m.RED)
    uniform.set_color(m.GREEN)
    np.testing.assert_array_equal(uniform.pos_to_rgb(np.zeros(3)), m.GREEN.to_rgb())
    assert uniform.pos_to_color(np.zeros(3)) == m.GREEN


def test_a_stream_lines_colors_run_from_its_start_to_its_end() -> None:
    lines = m.StreamLines(
        lambda p: np.array([1.0, 0.5, 0]), x_range=[-2, 2, 1], y_range=[-2, 2, 1]
    )
    for line in lines.stream_lines:  # straight: its ends are its box's corners
        np.testing.assert_allclose(
            line.get_gradient_start_and_end_points(),
            (line.get_start(), line.get_end()),
            atol=1e-9,
        )
