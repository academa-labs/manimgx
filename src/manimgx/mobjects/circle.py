from dataclasses import dataclass

from manimgx.mobjects.bases.planar_path import PlanarPath
from manimgx.mobjects.bases.planar_path_mobject import PlanarPathMobject
from manimgx.primitives.color import Opacity, StrokeWidth


@dataclass(kw_only=True, eq=False)
class Circle(PlanarPathMobject):
    radius: float = 1.0
    color: str = "#fc6255"
    fill_opacity: Opacity = 0.0
    stroke_width: StrokeWidth = 4.0

    def _create_planar_path(self, path: PlanarPath) -> None:
        path.circle(self.radius)
