from dataclasses import dataclass

from manimgx.mobjects.bases.planar_path import PlanarPath
from manimgx.mobjects.bases.planar_path_mobject import PlanarPathMobject
from manimgx.primitives.color import Opacity, StrokeWidth


@dataclass(kw_only=True, eq=False)
class Ellipse(PlanarPathMobject):
    width: float = 2.0
    height: float = 1.0
    fill_opacity: Opacity = 0.0
    stroke_width: StrokeWidth = 4.0

    def _create_planar_path(self, path: PlanarPath) -> None:
        path.ellipse(self.width / 2, self.height / 2)
