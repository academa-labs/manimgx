from dataclasses import dataclass

from manimgx.mobjects.bases.planar_path import PlanarPath
from manimgx.mobjects.bases.planar_path_mobject import PlanarPathMobject
from manimgx.primitives.units import Angle


@dataclass(kw_only=True, eq=False)
class Arrow(PlanarPathMobject):
    length: float = 2.0
    shaft_width: float = 0.06
    tip_length: float = 0.3
    tip_width: float = 0.25
    angle: Angle = 0.0

    def _create_planar_path(self, path: "PlanarPath") -> None:
        half_length = self.length / 2
        shaft_left = -half_length
        shaft_right = half_length - self.tip_length
        hw = self.shaft_width / 2
        tw = self.tip_width / 2
        tip_x = half_length

        path.polygon(
            [
                (shaft_left, -hw),
                (shaft_right, -hw),
                (shaft_right, -tw),
                (tip_x, 0.0),
                (shaft_right, tw),
                (shaft_right, hw),
                (shaft_left, hw),
            ]
        )
        path.rotate(self.angle)
