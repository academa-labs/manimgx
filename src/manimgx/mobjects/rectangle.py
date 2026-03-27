from dataclasses import dataclass

from manimgx.mobjects.bases.planar_path import PlanarPath
from manimgx.mobjects.bases.planar_path_mobject import PlanarPathMobject
from manimgx.primitives.color import Opacity, StrokeWidth


@dataclass(kw_only=True, eq=False)
class Rectangle(PlanarPathMobject):
    width: float = 4.0
    height: float = 2.0
    fill_opacity: Opacity = 0.0
    stroke_width: StrokeWidth = 4.0

    def _create_planar_path(self, path: PlanarPath) -> None:
        path.rectangle(self.width, self.height)
