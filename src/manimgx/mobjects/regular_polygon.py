from dataclasses import dataclass

from manimgx.mobjects.bases.planar_path import PlanarPath
from manimgx.mobjects.bases.planar_path_mobject import PlanarPathMobject
from manimgx.primitives.color import Opacity, StrokeWidth


@dataclass(kw_only=True, eq=False)
class RegularPolygon(PlanarPathMobject):
    n: int = 5
    radius: float = 1.0
    color: str = "#58c4dd"
    fill_opacity: Opacity = 0.0
    stroke_width: StrokeWidth = 4.0

    def _create_planar_path(self, path: PlanarPath) -> None:
        path.regular_polygon(self.radius, self.n)
