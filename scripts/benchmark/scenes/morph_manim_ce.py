"""A rippling surface, rebuilt every frame, with the camera circling it. (Manim Community
Edition.)"""

from manim import *


class Morph(ThreeDScene):
    def construct(self) -> None:
        axes = ThreeDAxes(
            x_range=[-3, 3, 1],
            y_range=[-3, 3, 1],
            z_range=[-2, 2, 1],
            x_length=7,
            y_length=7,
            z_length=4,
        )
        phase = ValueTracker(0)
        surface = always_redraw(
            lambda: Surface(
                lambda u, v: axes.c2p(
                    u, v, 0.8 * np.sin(2 * np.hypot(u, v) - phase.get_value())
                ),
                u_range=[-3, 3],
                v_range=[-3, 3],
                resolution=(48, 48),
                checkerboard_colors=[BLUE_D, BLUE_E],
            )
        )
        self.set_camera_orientation(phi=65 * DEGREES, theta=-45 * DEGREES)
        self.add(axes, surface)
        self.begin_ambient_camera_rotation(rate=0.3)
        self.play(phase.animate.set_value(4 * np.pi), run_time=10, rate_func=linear)
