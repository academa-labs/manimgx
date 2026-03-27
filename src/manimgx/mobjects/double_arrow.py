from dataclasses import dataclass

from manimgx.mobjects.arrow import Arrow
from manimgx.mobjects.bases.planar_path import PlanarPath


@dataclass(kw_only=True, eq=False)
class DoubleArrow(Arrow):
    def _create_planar_path(self, path: PlanarPath) -> None:
        hl = self.length / 2
        hw = self.shaft_width / 2
        tl = self.tip_length
        tw = self.tip_width / 2

        path.polygon(
            [
                (-hl, 0.0),
                (-(hl - tl), -tw),
                (-(hl - tl), -hw),
                (hl - tl, -hw),
                (hl - tl, -tw),
                (hl, 0.0),
                (hl - tl, tw),
                (hl - tl, hw),
                (-(hl - tl), hw),
                (-(hl - tl), tw),
            ]
        )
        path.rotate(self.angle)
