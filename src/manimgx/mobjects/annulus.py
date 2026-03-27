from dataclasses import dataclass

from manimgx.mobjects.bases.planar_path import PlanarPath
from manimgx.mobjects.bases.planar_path_mobject import PlanarPathMobject


@dataclass(kw_only=True, eq=False)
class Annulus(PlanarPathMobject):
    inner_radius: float = 0.5
    outer_radius: float = 1.0

    def _create_planar_path(self, path: "PlanarPath") -> None:
        path.circle(self.outer_radius)
        path.ellipse(self.inner_radius, -self.inner_radius)
