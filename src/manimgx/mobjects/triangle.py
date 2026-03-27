from dataclasses import dataclass

from manimgx.mobjects.regular_polygon import RegularPolygon


@dataclass(kw_only=True, eq=False)
class Triangle(RegularPolygon):
    n: int = 3
