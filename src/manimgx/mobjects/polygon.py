from dataclasses import dataclass

from manimgx.mobjects.bases.planar_path import PlanarPath
from manimgx.mobjects.bases.planar_path_mobject import PlanarPathMobject
from manimgx.primitives.color import Color, Opacity


@dataclass(kw_only=True, init=False, eq=False)
class Polygon(PlanarPathMobject):
    vertices: tuple[tuple[float, float], ...]

    def __init__(
        self,
        *vertices: tuple[float, float],
        color: Color = "white",
        fill_opacity: Opacity = 1.0,
    ) -> None:
        self.vertices = vertices
        super().__init__(color=color, fill_opacity=fill_opacity)

    def _create_planar_path(self, path: PlanarPath) -> None:
        path.polygon(self.vertices)
