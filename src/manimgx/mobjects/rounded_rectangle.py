from dataclasses import dataclass

from manimgx.mobjects.bases.planar_path import PlanarPath
from manimgx.mobjects.rectangle import Rectangle


@dataclass(kw_only=True, eq=False)
class RoundedRectangle(Rectangle):
    corner_radius: float = 0.25

    def _create_planar_path(self, path: PlanarPath) -> None:
        path.rounded_rectangle(self.width, self.height, self.corner_radius)
