import math
from dataclasses import dataclass

from manimgx.mobjects.bases.planar_path import PlanarPath
from manimgx.mobjects.bases.planar_path_mobject import PlanarPathMobject
from manimgx.primitives.units import Angle


@dataclass(kw_only=True, eq=False)
class AnnularSector(PlanarPathMobject):
    inner_radius: float = 0.5
    outer_radius: float = 1.0
    start_angle: Angle = 0.0
    angle: Angle = math.tau / 4

    def _create_planar_path(self, path: "PlanarPath") -> None:
        end_angle = self.start_angle + self.angle

        path.move_to(
            self.inner_radius * math.cos(self.start_angle),
            self.inner_radius * math.sin(self.start_angle),
        )

        if self.inner_radius > 1e-12:
            path.arc_to(self.inner_radius, self.start_angle, self.angle)

        path.line_to(
            self.outer_radius * math.cos(end_angle),
            self.outer_radius * math.sin(end_angle),
        )

        path.arc_to(self.outer_radius, end_angle, -self.angle)

        path.close()
