import math
from dataclasses import dataclass

from manimgx.mobjects.bases.planar_path import PlanarPath
from manimgx.mobjects.bases.planar_path_mobject import PlanarPathMobject
from manimgx.primitives.units import Angle


@dataclass(kw_only=True, eq=False)
class CurvedArrow(PlanarPathMobject):
    radius: float = 1.0
    start_angle: Angle = 0.0
    angle: Angle = math.tau / 3
    shaft_width: float = 0.06
    tip_length: float = 0.2
    tip_width: float = 0.2

    def _create_planar_path(self, path: "PlanarPath") -> None:
        r = self.radius
        r_inner = r - self.shaft_width / 2
        r_outer = r + self.shaft_width / 2
        tip_angle = self.tip_length / r

        shaft_start = self.start_angle
        shaft_end = self.start_angle + self.angle - tip_angle
        shaft_arc = shaft_end - shaft_start

        arrow_tip_angle = self.start_angle + self.angle

        path.move_to(
            r_outer * math.cos(shaft_start),
            r_outer * math.sin(shaft_start),
        )

        path.arc_to(r_outer, shaft_start, shaft_arc)

        arrow_base_outer_r = r + self.tip_width / 2
        path.line_to(
            arrow_base_outer_r * math.cos(shaft_end),
            arrow_base_outer_r * math.sin(shaft_end),
        )

        path.line_to(
            r * math.cos(arrow_tip_angle),
            r * math.sin(arrow_tip_angle),
        )

        arrow_base_inner_r = r - self.tip_width / 2
        path.line_to(
            arrow_base_inner_r * math.cos(shaft_end),
            arrow_base_inner_r * math.sin(shaft_end),
        )

        path.arc_to(r_inner, shaft_end, -shaft_arc)

        path.close()
