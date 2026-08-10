"""A classic explainer: a curve drawn on axes, its area and its integral, then a tangent
line sliding along it. (ManimGL.)"""

import numpy as np
from manimlib import *

YELLOW = "#F7D96F"  # Manim CE's color, where ManimGL's differs


class Explainer(Scene):
    default_camera_config = {"background_color": BLACK}

    def construct(self) -> None:
        axes = Axes(
            x_range=(0, 2 * np.pi, np.pi / 2),
            y_range=(-1.5, 1.5, 1),
            width=12,
            height=6,
            axis_config={"include_tip": True},  # Manim CE's defaults
        )
        # The graph's x_range is given without a step: get_area_under_graph fails on one
        # with a step (ManimGL 1.7.2).
        sine = axes.get_graph(
            np.sin, x_range=(0, 2 * np.pi), color=BLUE, stroke_width=6
        )
        dot = Dot(axes.i2gp(0, sine), radius=0.12, fill_color=YELLOW)
        area = axes.get_area_under_graph(
            sine, x_range=(0, np.pi), fill_color=BLUE, fill_opacity=0.4
        )
        label = Tex(r"y = \sin x", font_size=72).to_corner(UR)
        integral = Tex(r"\int_0^\pi \sin x \, dx = 2", font_size=72).to_corner(UR)
        self.play(ShowCreation(axes), Write(label))
        self.play(ShowCreation(sine), MoveAlongPath(dot, sine), run_time=2.5)
        self.play(
            FadeIn(area), TransformMatchingTex(label, integral, run_time=1)
        )  # 2 s by default
        along = ValueTracker(0)
        tangent = always_redraw(
            lambda: TangentLine(sine, alpha=along.get_value(), length=3, color=YELLOW)
        )
        dot.add_updater(
            lambda d: d.move_to(sine.point_from_proportion(along.get_value()))
        )
        self.add(tangent, dot)
        self.play(along.animate.set_value(1), run_time=4)
        self.wait()
