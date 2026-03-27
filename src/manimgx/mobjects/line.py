from dataclasses import dataclass

from manimgx.mobjects.bases.planar_path import PlanarPath
from manimgx.mobjects.bases.planar_path_mobject import PlanarPathMobject
from manimgx.primitives.units import Angle


@dataclass(kw_only=True, eq=False)
class Line(PlanarPathMobject):
    length: float = 2.0
    thickness: float = 0.04
    angle: Angle = 0.0

    def _create_planar_path(self, path: "PlanarPath") -> None:
        path.rectangle(self.length, self.thickness)
        path.rotate(self.angle)
