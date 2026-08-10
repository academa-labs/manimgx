"""A rippling surface, rebuilt every frame, with the camera circling it. (ManimGL.)"""

import tempfile

import numpy as np
from manimlib import *
from PIL import Image

BLUE_E = "#236B8E"  # Manim CE's color, where ManimGL's differs


def checkerboard(colors: list[str], cells: int = 48, px: int = 16) -> str:
    """A PNG of `cells` x `cells` squares: ManimGL's surfaces take one color, so the
    checkerboard is painted on as a texture (face (i, j) gets colors[(i + j) % 2])."""
    a, b = (color_to_int_rgb(c) for c in colors)
    rows, cols = np.indices((cells, cells))
    image = np.where(((rows + cols + 1) % 2 == 0)[..., None], a, b).astype(np.uint8)
    path = f"{tempfile.gettempdir()}/checkerboard.png"
    Image.fromarray(image.repeat(px, 0).repeat(px, 1)).save(path)
    return path


class Morph(ThreeDScene):
    default_camera_config = {"background_color": BLACK}

    def construct(self) -> None:
        axes = ThreeDAxes(
            x_range=(-3, 3, 1),
            y_range=(-3, 3, 1),
            z_range=(-2, 2, 1),
            width=7,
            height=7,
            depth=4,
            axis_config={"include_tip": True},
        )
        phase = ValueTracker(0)
        texture = checkerboard([BLUE_D, BLUE_E])
        surface = always_redraw(
            lambda: TexturedSurface(
                ParametricSurface(
                    lambda u, v: axes.c2p(
                        u, v, 0.8 * np.sin(2 * np.hypot(u, v) - phase.get_value())
                    ),
                    u_range=(-3, 3),
                    v_range=(-3, 3),
                    resolution=(49, 49),  # sample points: 48 x 48 squares
                ),
                texture,
            )
        )
        self.frame.reorient(45, 65)  # ManimGL's theta is Manim CE's plus 90 degrees
        self.frame.set_focal_distance(20)  # Manim CE's camera distance
        self.add(axes, surface)
        self.frame.add_updater(lambda frame, dt: frame.increment_theta(0.3 * dt))
        self.play(phase.animate.set_value(4 * np.pi), run_time=10, rate_func=linear)
