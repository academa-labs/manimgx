"""A classic explainer: a curve drawn on axes, its area and its integral, then a tangent
line sliding along it. (Manim Community Edition.)"""

from manim import *


class Explainer(Scene):
    def construct(self) -> None:
        axes = Axes(x_range=[0, 2 * np.pi, np.pi / 2], y_range=[-1.5, 1.5, 1])
        sine = axes.plot(np.sin, color=BLUE, stroke_width=6)
        dot = Dot(axes.i2gp(0, sine), radius=0.12, color=YELLOW)
        area = axes.get_area(sine, x_range=(0, np.pi), color=BLUE, opacity=0.4)
        label = MathTex(r"y = \sin x", font_size=72).to_corner(UR)
        integral = MathTex(r"\int_0^\pi \sin x \, dx = 2", font_size=72).to_corner(UR)
        self.play(Create(axes), Write(label))
        self.play(Create(sine), MoveAlongPath(dot, sine), run_time=2.5)
        self.play(FadeIn(area), TransformMatchingTex(label, integral))
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
