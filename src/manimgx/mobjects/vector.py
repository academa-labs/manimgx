import math
from dataclasses import dataclass

from manimgx.mobjects.bases.planar_path import PlanarPath
from manimgx.mobjects.bases.planar_path_mobject import PlanarPathMobject


@dataclass(kw_only=True, eq=False)
class Vector(PlanarPathMobject):
    dx: float = 1.0
    dy: float = 0.0
    shaft_width: float = 0.06
    tip_length: float = 0.25
    tip_width: float = 0.2

    def _create_planar_path(self, path: PlanarPath) -> None:
        length = math.sqrt(self.dx**2 + self.dy**2)
        if length < 1e-9:
            return

        angle = math.atan2(self.dy, self.dx)
        hw = self.shaft_width / 2
        tl = min(self.tip_length, length * 0.5)
        tw = self.tip_width / 2
        shaft_end = length - tl

        path.polygon(
            [
                (0, -hw),
                (shaft_end, -hw),
                (shaft_end, -tw),
                (length, 0),
                (shaft_end, tw),
                (shaft_end, hw),
                (0, hw),
            ]
        )
        path.rotate(angle)
