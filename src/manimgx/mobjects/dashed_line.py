from dataclasses import dataclass

from manimgx.mobjects.bases.planar_path import PlanarPath
from manimgx.mobjects.bases.planar_path_mobject import PlanarPathMobject
from manimgx.primitives.units import Angle


@dataclass(kw_only=True, eq=False)
class DashedLine(PlanarPathMobject):
    length: float = 2.0
    thickness: float = 0.04
    dash_length: float = 0.15
    gap_length: float = 0.1
    angle: Angle = 0.0

    def _create_planar_path(self, path: PlanarPath) -> None:
        half_total = self.length / 2
        step = self.dash_length + self.gap_length
        pos = -half_total

        while pos + self.dash_length <= half_total + 1e-9:
            x1 = min(pos + self.dash_length, half_total)
            center_x = (pos + x1) / 2
            width = x1 - pos
            path.rectangle(width, self.thickness, x=center_x)
            pos += step

        path.rotate(self.angle)
